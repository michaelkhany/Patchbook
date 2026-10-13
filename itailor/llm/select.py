# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
Choosing the most suitable model, deterministically and with an explanation.

Method (design §8 and §11.2):

1. **Hard filters** drop candidates that violate a constraint: remote models
   under ``local_only``; models that cannot emit native tool calls and are
   too small to be trusted with the text protocol; context below the task
   estimate; local models that do not fit in memory.
2. **Ranking** by a weighted sum (simple additive weighting, Hwang & Yoon
   1981) over criteria normalised to [0, 1]. The weights are derived from a
   pairwise-comparison matrix with the Analytic Hierarchy Process (Saaty
   1980), including its consistency ratio: a matrix with CR > 0.1 is
   rejected at import time, so an inconsistent judgement cannot become a
   silent default.
3. **Roles**: planner (strongest reasoning), coder (coder-family fit),
   summarizer (smallest adequate). One model fills all three when that is
   all there is.
4. **Fallback chain**: the runner-up per role.
5. **Online adaptation** (optional, off by default): Thompson sampling over
   a Beta posterior per model (Thompson 1933), rewarded by *verified* step
   success. It never overrides the hard filters.

Local-model fit is memory arithmetic (weights + KV cache + buffers, as
llama.cpp/PagedAttention size it) and decode speed is a roofline estimate:
tokens/s ≈ memory bandwidth / bytes of active weights per token (Williams et
al. 2009). Both are reported as estimates with their assumptions.

Every constant below carries a provenance line.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
from dataclasses import dataclass, field, asdict

from . import providers

# ---------------------------------------------------------------------------
# Criteria and AHP weights
# ---------------------------------------------------------------------------
CRITERIA = ("tools", "context", "family", "speed", "cost")

# Saaty's random consistency index, n = 1..10 (Saaty 1980, Table 1.7).
RANDOM_INDEX = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}

# Pairwise judgements on Saaty's 1-9 scale, row vs column: "how much more
# important is the row criterion than the column criterion for choosing a
# model that will write and repair code". Provenance: author judgement,
# 2026-10-12, uncalibrated; to be revisited against the evaluation suite
# (design §11.4). CR is checked below.
DEFAULT_PAIRWISE = [
    # tools  context family speed cost
    [1,      2,      2,     4,    4],    # tools: native tool calling is the mechanism's lifeline
    [1 / 2,  1,      1,     3,    3],    # context: long runs need long memory
    [1 / 2,  1,      1,     3,    3],    # family: a coder/reasoner fits the role
    [1 / 4,  1 / 3,  1 / 3, 1,    1],    # speed
    [1 / 4,  1 / 3,  1 / 3, 1,    1],    # cost
]


def ahp_weights(matrix: list[list[float]]) -> tuple[list[float], float]:
    """Priority vector (geometric-mean approximation of the principal
    eigenvector) and consistency ratio for a pairwise matrix."""
    n = len(matrix)
    if n == 0:
        return [], 0.0
    geo = [math.prod(row) ** (1.0 / n) for row in matrix]
    total = sum(geo)
    weights = [g / total for g in geo]
    # lambda_max ≈ mean over rows of (A·w)_i / w_i
    aw = [sum(matrix[i][j] * weights[j] for j in range(n)) for i in range(n)]
    lambda_max = sum(aw[i] / weights[i] for i in range(n)) / n
    ci = (lambda_max - n) / (n - 1) if n > 1 else 0.0
    ri = RANDOM_INDEX.get(n, 1.49)
    cr = ci / ri if ri else 0.0
    return weights, cr


_weights, _cr = ahp_weights(DEFAULT_PAIRWISE)
if _cr > 0.1:  # Saaty's acceptance threshold
    raise RuntimeError(f"DEFAULT_PAIRWISE is inconsistent (CR={_cr:.3f} > 0.1); fix the judgements.")
DEFAULT_WEIGHTS = dict(zip(CRITERIA, _weights))
DEFAULT_CONSISTENCY_RATIO = _cr


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------
@dataclass
class Candidate:
    model: str
    source_id: str
    base_url: str = ""
    local: bool = False
    context: int = 0                   # tokens; 0 = unknown
    native_tools: bool | None = None   # None = not probed
    params_b: float | None = None      # billions of parameters, from the name
    price: tuple | None = None         # USD per 1M tokens (in, out); None = unknown
    est_tps: float | None = None       # estimated decode tokens/s (local)
    fits: bool | None = None           # local: fits in memory?
    tags: list = field(default_factory=list)


@dataclass
class TaskProfile:
    context_needed: int = 16000        # tokens; provenance: default for a mid-size project, uncalibrated
    needs_tools: bool = True
    role_hints: dict = field(default_factory=dict)


@dataclass
class Constraints:
    local_only: bool = False
    max_price_out: float | None = None     # USD per 1M output tokens
    exclude: list = field(default_factory=list)
    include_only: list = field(default_factory=list)
    allow_text_protocol: bool = True


@dataclass
class Selection:
    roles: dict                     # role -> model id
    role_sources: dict              # role -> source id
    ranked: list                    # [{model, score, criteria, source}]
    fallbacks: dict                 # role -> [model ids]
    filtered_out: list              # [(model, reason)]
    explanation: list               # human lines
    weights: dict
    consistency_ratio: float

    def to_dict(self) -> dict:
        return asdict(self)


_PARAMS_RE = re.compile(r"(?<![a-z0-9])(\d{1,3}(?:\.\d)?)\s*b(?![a-z0-9])", re.IGNORECASE)
_MOE_RE = re.compile(r"a(\d{1,2}(?:\.\d)?)b", re.IGNORECASE)

# Family preferences per role. Provenance: Patch Code modelselect.js PREFERRED
# list, split by role; author judgement, uncalibrated.
FAMILY = {
    "coder": [re.compile(p, re.I) for p in (r"coder", r"devstral", r"codestral", r"gpt-5", r"gpt-4\.1",
                                            r"deepseek-chat", r"deepseek-v", r"qwen3", r"glm", r"gpt-oss",
                                            r"mistral-large", r"llama-3\.[3-9]", r"gemma")],
    "planner": [re.compile(p, re.I) for p in (r"reasoner", r"r1", r"^o[34]", r"gpt-5", r"think", r"opus",
                                              r"deepseek-v", r"qwen3", r"glm", r"gpt-oss", r"devstral",
                                              r"mistral-large", r"llama-3\.[3-9]")],
    "summarizer": [re.compile(p, re.I) for p in (r"mini", r"flash", r"small", r"nano", r"lite", r"haiku",
                                                 r"7b", r"8b", r"9b", r"4b", r"3b", r"gemma", r"qwen")],
}

# Text-protocol floor: below this many parameters a model without native tool
# calling is not trusted to follow the <tool> block protocol. Provenance:
# experience with DAYA's local models (Qwen2.5 1.5B/3B fail it); uncalibrated.
TEXT_PROTOCOL_MIN_PARAMS_B = 7.0


def params_from_name(model: str) -> float | None:
    name = str(model or "")
    moe = _MOE_RE.search(name)
    if moe:
        return float(moe.group(1))        # active parameters are what cost per token
    match = _PARAMS_RE.search(name)
    return float(match.group(1)) if match else None


def family_fit(model: str, role: str) -> float:
    patterns = FAMILY.get(role, [])
    for index, pattern in enumerate(patterns):
        if pattern.search(model):
            return 1.0 - index / max(1, len(patterns))
    return 0.0


# ---------------------------------------------------------------------------
# Local fit and speed
# ---------------------------------------------------------------------------
def local_fit(size_gb: float, *, ram_gb: float, vram_gb: float = 0.0, ctx: int = 16384,
              kv_kb_per_token: float = 64.0, active_gb: float | None = None,
              bandwidth_gbs: float | None = None) -> dict:
    """Memory arithmetic and a roofline speed estimate for a local model.

    need = weights + KV cache + 0.6 GB compute buffers (llama.cpp's typical
    overhead; provenance: DAYA local_llm.assess). KV per token comes from the
    model card (2 · layers · hidden · bytes). Speed: bandwidth / bytes touched
    per token; bandwidth defaults are 20 GB/s for a laptop CPU, 90 GB/s for
    Apple Silicon unified memory, 300 GB/s for a discrete GPU with the model
    in VRAM (provenance: DAYA local_llm.assess and public hardware specs;
    coarse, uncalibrated).
    """
    kv = kv_kb_per_token * ctx / (1024 * 1024)
    need = size_gb + kv + 0.6
    if bandwidth_gbs is None:
        bandwidth_gbs = 300.0 if vram_gb and vram_gb >= need else 20.0
    active = active_gb if active_gb else size_gb
    tps = bandwidth_gbs / max(0.3, active)
    fits = (vram_gb >= need) or (ram_gb >= need + 1.0)
    headroom = max(ram_gb, vram_gb) - need
    return {"needGb": round(need, 1), "fits": fits, "headroomGb": round(headroom, 1),
            "estTokensPerSecond": round(tps, 1), "assumptions":
            f"bandwidth {bandwidth_gbs:.0f} GB/s, ctx {ctx}, KV {kv_kb_per_token} KB/token, +0.6 GB buffers"}


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------
def _normalise(values: list[float]) -> list[float]:
    finite = [v for v in values if v is not None]
    if not finite:
        return [0.5 for _ in values]
    lo, hi = min(finite), max(finite)
    if hi - lo < 1e-9:
        return [1.0 if v is not None else 0.5 for v in values]
    return [((v - lo) / (hi - lo)) if v is not None else 0.5 for v in values]


def score_candidates(candidates: list[Candidate], role: str, weights: dict | None = None) -> list[dict]:
    weights = weights or DEFAULT_WEIGHTS
    if not candidates:
        return []
    # tools: 1 native, 0.5 unknown (would be probed), 0.2 text protocol
    tools = [1.0 if c.native_tools else (0.5 if c.native_tools is None else 0.2) for c in candidates]
    # context: log scale, unknown = None -> 0.5 after normalisation
    context = _normalise([math.log(c.context) if c.context > 0 else None for c in candidates])
    family = [family_fit(c.model, role) for c in candidates]
    # speed: local estimate normalised; hosted unknown -> 1.0 (assumed fast) - uncalibrated
    speed_raw = [c.est_tps if c.local else None for c in candidates]
    speed_norm = _normalise(speed_raw)
    speed = [speed_norm[i] if candidates[i].local else 1.0 for i in range(len(candidates))]
    # cost: inverse of output price; local = free = 1.0; unknown = 0.5
    cost_raw = [(-c.price[1]) if c.price is not None else None for c in candidates]
    cost_norm = _normalise(cost_raw)
    cost = [1.0 if c.local else (cost_norm[i] if c.price is not None else 0.5)
            for i, c in enumerate(candidates)]
    rows = []
    for i, c in enumerate(candidates):
        crit = {"tools": tools[i], "context": context[i], "family": family[i], "speed": speed[i], "cost": cost[i]}
        score = sum(weights[k] * crit[k] for k in CRITERIA)
        rows.append({"model": c.model, "source": c.source_id, "score": round(score, 4),
                     "criteria": {k: round(v, 3) for k, v in crit.items()}, "local": c.local,
                     "context": c.context, "nativeTools": c.native_tools})
    rows.sort(key=lambda r: (-r["score"], r["model"]))
    return rows


def hard_filter(candidates: list[Candidate], task: TaskProfile, constraints: Constraints) -> tuple[list, list]:
    kept, dropped = [], []
    excluded = {str(x).lower() for x in constraints.exclude}
    only = {str(x).lower() for x in constraints.include_only}
    for c in candidates:
        name = c.model.lower()
        if only and name not in only:
            dropped.append((c.model, "not in include list"))
        elif name in excluded:
            dropped.append((c.model, "excluded by settings"))
        elif constraints.local_only and not c.local:
            dropped.append((c.model, "remote model under local-only privacy constraint"))
        elif task.needs_tools and c.native_tools is False and (
                not constraints.allow_text_protocol
                or (c.params_b is not None and c.params_b < TEXT_PROTOCOL_MIN_PARAMS_B)):
            dropped.append((c.model, "no native tool calling and too small for the text protocol"))
        elif c.context and task.context_needed and c.context < task.context_needed:
            dropped.append((c.model, f"context {c.context} below the task estimate {task.context_needed}"))
        elif c.local and c.fits is False:
            dropped.append((c.model, "does not fit in this machine's memory"))
        elif constraints.max_price_out is not None and c.price is not None and c.price[1] > constraints.max_price_out:
            dropped.append((c.model, f"output price {c.price[1]} above the ceiling {constraints.max_price_out}"))
        else:
            kept.append(c)
    return kept, dropped


def select(candidates: list[Candidate], task: TaskProfile | None = None,
           constraints: Constraints | None = None, weights: dict | None = None,
           bandit: "BanditSelector | None" = None) -> Selection:
    task = task or TaskProfile()
    constraints = constraints or Constraints()
    weights = weights or DEFAULT_WEIGHTS
    kept, dropped = hard_filter(candidates, task, constraints)
    explanation = [f"{len(candidates)} candidate(s); {len(dropped)} removed by hard filters."]
    for model, reason in dropped:
        explanation.append(f"  - {model}: {reason}")
    roles: dict = {}
    role_sources: dict = {}
    fallbacks: dict = {}
    ranked_all = score_candidates(kept, "coder", weights)
    for role in ("planner", "coder", "summarizer"):
        ranked = score_candidates(kept, role, weights)
        if bandit is not None and ranked:
            ranked = bandit.rerank(ranked)
        if not ranked:
            continue
        roles[role] = ranked[0]["model"]
        role_sources[role] = ranked[0]["source"]
        fallbacks[role] = [r["model"] for r in ranked[1:4]]
        top = ranked[0]
        explanation.append(
            f"{role}: {top['model']} (score {top['score']:.3f}; "
            + ", ".join(f"{k}={v:.2f}" for k, v in top["criteria"].items()) + ")")
    explanation.append("weights: " + ", ".join(f"{k}={v:.3f}" for k, v in weights.items())
                       + f" (AHP, CR={DEFAULT_CONSISTENCY_RATIO:.3f}; provenance: author judgement, uncalibrated)")
    if not roles:
        explanation.append("No candidate survived the filters.")
    return Selection(roles=roles, role_sources=role_sources, ranked=ranked_all, fallbacks=fallbacks,
                     filtered_out=dropped, explanation=explanation, weights=dict(weights),
                     consistency_ratio=DEFAULT_CONSISTENCY_RATIO)


def candidates_from_sources(sources, capabilities: dict | None = None, machine: dict | None = None) -> list[Candidate]:
    """Turn discovered sources into candidates (see ``itailor.llm.discover``)."""
    capabilities = capabilities or {}
    out: list[Candidate] = []
    for source in sources:
        if getattr(source, "kind", "") == "local-file":
            continue
        models = list(source.models) or ([source.model] if source.model else [])
        for model in models:
            key = f"{source.base_url}|{model}"
            cap = capabilities.get(key)
            native = cap.get("nativeToolCalling") if isinstance(cap, dict) else None
            if native is None:
                native = providers.known_tool_support(source.base_url, model)
            params = params_from_name(model)
            candidate = Candidate(model=model, source_id=source.id, base_url=source.base_url,
                                  local=bool(source.local), context=int(source.contexts.get(model, 0) or 0),
                                  native_tools=native, params_b=params,
                                  price=providers.price_hint(source.base_url, model))
            if candidate.local and params and machine:
                size_gb = params * 0.6     # Q4_K_M ≈ 0.6 GB per billion parameters (llama.cpp quant tables)
                fit = local_fit(size_gb, ram_gb=float(machine.get("ramTotalGb") or 0),
                                vram_gb=float(machine.get("vramGb") or 0))
                candidate.fits = fit["fits"]
                candidate.est_tps = fit["estTokensPerSecond"]
            out.append(candidate)
    return out


# ---------------------------------------------------------------------------
# Thompson sampling (optional)
# ---------------------------------------------------------------------------
class BanditSelector:
    """Beta-Bernoulli Thompson sampling over models, rewarded by verified success.

    Prior Beta(1, 1) (uniform). The sample is used only to re-order candidates
    that already passed the hard filters, and the static score breaks ties:
    the bandit cannot promote a model the filters rejected. Off by default
    (settings ``modelBandit``) because it needs dozens of runs to pay off.
    """

    def __init__(self, path: str | None = None, seed: int | None = None) -> None:
        self.path = path
        self.state: dict = {}
        self.random = random.Random(seed)
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    self.state = json.load(handle)
            except Exception:  # noqa: BLE001
                self.state = {}

    def save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(self.state, handle, indent=2)

    def update(self, model: str, success: bool) -> None:
        entry = self.state.setdefault(model, {"a": 1, "b": 1})
        entry["a" if success else "b"] += 1
        self.save()

    def sample(self, model: str) -> float:
        entry = self.state.get(model, {"a": 1, "b": 1})
        return self.random.betavariate(entry["a"], entry["b"])

    def rerank(self, ranked: list[dict]) -> list[dict]:
        drawn = [(self.sample(r["model"]) + r["score"], r) for r in ranked]
        drawn.sort(key=lambda pair: -pair[0])
        return [r for _s, r in drawn]
