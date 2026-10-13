# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
The policy engine: an ordered chain of deciders per gate, combined the way
XACML combines policies (deny-overrides across the chain, first-applicable
within it). Attribute-based (NIST SP 800-162): a decision is a function of
the action's attributes, the context, and the rules - never of a model.

Chain order (design §9.2):

  1. hard blocks  2. organisation policy  3. deny rules  4. risk scorer
  5. plan pre-approval  6. ask rules  7. allow rules  8. lessons (hints only)
  9. mode default

A ``deny`` anywhere wins. Otherwise the first decider that does not abstain
decides. The human (``ask``) is not a decider here: an ``ask`` verdict is the
engine's answer, and ``itailor.permissions`` takes it to the oversight
adapter. Every decider's answer is kept in a ``Trace`` for the transcript.
"""

from __future__ import annotations

import json
import os
import re
from typing import Callable, Protocol

from .decisions import (ABSTAIN, ALLOW, ASK, DENY, Action, Context, Decision, Trace)
from .rules import first_match
from . import risk as risk_module

# Commands never worth the risk, approval or not (DAYA patch_agent.HARD_BLOCK + Patch Code shell.js).
HARD_BLOCK = [re.compile(p, re.IGNORECASE) for p in (
    r"^\s*rm\s+(-[a-zA-Z]*\s+)*-?[rRf]{1,2}\s+(/|~|\*|\$HOME)(\s|$|\*)",
    r"^\s*rm\s+-[a-zA-Z]*[rR][a-zA-Z]*\s+.*(/|\\)\s*$",
    r"\bmkfs(\.|\s)",
    r"\bdd\s+.*of=/dev/(sd|nvme|hd)",
    r"^\s*(del|erase)\s+/[sfq].*[a-zA-Z]:\\(\s|$|\*)",
    r"\bformat\s+[a-zA-Z]:",
    r"\bdiskpart\b",
    r"\bshutdown\b",
    r"\b(Stop|Restart)-Computer\b",
    r"\bRemove-Item\b.*-Recurse.*(\\|/)\s*$",
    r"\bgit\s+push\s+.*--force\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-[a-zA-Z]*f",
    r"\bgit\s+checkout\s+--\s+\.",
    r":\(\)\s*\{\s*:\|:&\s*\};:",
    r"\bchmod\s+(-R\s+)?777\s+/",
)]


def is_destructive(text: str) -> bool:
    s = str(text or "")
    return any(p.search(s) for p in HARD_BLOCK)


class Decider(Protocol):
    name: str

    def decide(self, action: Action, context: Context) -> Decision | None: ...


class HardBlockDecider:
    name = "hard-block"

    def decide(self, action: Action, context: Context) -> Decision | None:
        if action.destructive or is_destructive(action.command) or (
                action.tool == "RunCode" and is_destructive(str(action.args.get("code") or ""))
                and re.search(r"\b(rm|del|format|mkfs|diskpart)\b", str(action.args.get("code") or ""), re.I)):
            return Decision(DENY, "destructive command (hard block)", self.name)
        return None


class OrgPolicyDecider:
    """An admin-owned policy file: ``{"deny": [rules], "localOnly": bool,
    "forbidNetwork": bool, "forbiddenProviders": [...]}``. Read from the path
    in ``ITAILOR_ORG_POLICY`` or the one given."""
    name = "org-policy"

    def __init__(self, policy: dict | None = None, path: str | None = None) -> None:
        self.policy = policy or {}
        self.path = path or os.environ.get("ITAILOR_ORG_POLICY", "")
        if not policy and self.path and os.path.isfile(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                self.policy = loaded if isinstance(loaded, dict) else {}
            except Exception:  # noqa: BLE001
                self.policy = {}

    def decide(self, action: Action, context: Context) -> Decision | None:
        if not self.policy:
            return None
        rule = first_match(self.policy.get("deny"), action.tool, action.args)
        if rule:
            return Decision(DENY, f"organisation policy denies {rule}", self.name)
        if self.policy.get("forbidNetwork") and (action.klass == "network" or action.egress
                                                 or action.tool in ("WebSearch", "WebFetch")):
            return Decision(DENY, "organisation policy forbids network access", self.name)
        if action.gate == "model" and self.policy.get("localOnly") and not action.extra.get("local"):
            return Decision(DENY, "organisation policy: models must run locally", self.name)
        forbidden = {str(p).lower() for p in self.policy.get("forbiddenProviders") or []}
        if action.gate == "model" and str(action.extra.get("provider", "")).lower() in forbidden:
            return Decision(DENY, f"organisation policy forbids provider {action.extra.get('provider')}", self.name)
        return None


class RulesDecider:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.name = f"{kind}-rules"

    def decide(self, action: Action, context: Context) -> Decision | None:
        rule = first_match((context.rules or {}).get(self.kind), action.tool, action.args)
        if not rule:
            return None
        verdict = {"deny": DENY, "ask": ASK, "allow": ALLOW}[self.kind]
        return Decision(verdict, f"{self.kind} rule {rule}", self.name)


class RiskDecider:
    """High risk forces a question even when a rule would allow; very high
    risk with an irreversible, system-wide effect is refused."""
    name = "risk"

    def __init__(self, project_root: str = "", ask_at: str = "high", deny_at: str = "very_high") -> None:
        self.project_root = project_root
        self.ask_at = ask_at
        self.deny_at = deny_at

    def decide(self, action: Action, context: Context) -> Decision | None:
        assessment = risk_module.assess(action, self.project_root)
        order = [name for _limit, name in risk_module.LEVELS]
        level_index = order.index(assessment.level)
        if level_index >= order.index(self.deny_at) and assessment.factors["reversibility"] >= 5 \
                and assessment.factors["blastRadius"] >= 4 and context.mode != "bypassPermissions":
            return Decision(DENY, f"risk {assessment.level} (score {assessment.score}): irreversible outside the project",
                            self.name, risk=assessment.to_dict())
        if level_index >= order.index(self.ask_at) and context.mode != "bypassPermissions":
            return Decision(ASK, f"risk {assessment.level} (score {assessment.score}): " + "; ".join(assessment.notes),
                            self.name, risk=assessment.to_dict())
        # Not a verdict, but attach the assessment for the trace and the prompt.
        return Decision(ABSTAIN, f"risk {assessment.level} (score {assessment.score})", self.name,
                        risk=assessment.to_dict())


class PlanPreapprovalDecider:
    name = "plan-preapproval"

    def decide(self, action: Action, context: Context) -> Decision | None:
        if context.plan_approved and action.signature in (context.approved_signatures or set()):
            return Decision(ALLOW, "declared in the approved plan", self.name)
        return None


class LessonsDecider:
    """Lessons inform; they never authorise (design §2.6). This decider
    abstains but attaches hints the permission prompt shows."""
    name = "lessons"

    def decide(self, action: Action, context: Context) -> Decision | None:
        hints = []
        for lesson in context.lessons or []:
            decision = str(lesson.get("decision") or "")
            rationale = str(lesson.get("rationale") or "")
            if decision:
                hints.append(f"earlier you answered '{decision}' in a similar situation"
                             + (f": {rationale}" if rationale else ""))
        if not hints:
            return None
        return Decision(ABSTAIN, "lesson hints attached", self.name, hints=hints)


class ModeDecider:
    name = "mode"

    def decide(self, action: Action, context: Context) -> Decision | None:
        mode = context.mode or "default"
        klass = action.klass
        if mode == "plan" and klass not in ("read", "human", "plan", "step", "consult", "lesson", "budget", "model"):
            return Decision(DENY, "plan mode: read-only", self.name)
        if mode == "bypassPermissions":
            return Decision(ALLOW, "bypassPermissions mode", self.name)
        if klass in ("read", "plan", "step", "model", "budget"):
            return Decision(ALLOW, "read-only or informational", self.name)
        if klass == "edit" and mode == "acceptEdits":
            return Decision(ALLOW, "acceptEdits mode", self.name)
        if klass == "shell" and action.read_only:
            return Decision(ALLOW, "read-only command", self.name)
        if klass in ("human", "consult"):
            return Decision(ASK, "consultation goes to the human", self.name)
        return Decision(ASK, f"{klass} needs confirmation", self.name)


class PolicyEngine:
    def __init__(self, deciders: list, combining: str = "deny-overrides") -> None:
        self.deciders = list(deciders)
        self.combining = combining

    def evaluate(self, action: Action, context: Context) -> tuple[Decision, Trace]:
        trace = Trace()
        first: Decision | None = None
        hints: list = []
        risk: dict | None = None
        for decider in self.deciders:
            try:
                decision = decider.decide(action, context)
            except Exception as exc:  # noqa: BLE001 - a broken decider must fail closed
                decision = Decision(DENY, f"{decider.name} failed: {exc}", decider.name)
            trace.add(getattr(decider, "name", type(decider).__name__), decision)
            if decision is None:
                continue
            if decision.hints:
                hints.extend(decision.hints)
            if decision.risk and risk is None:
                risk = decision.risk
            if decision.verdict == ABSTAIN:
                continue
            if decision.verdict == DENY and self.combining == "deny-overrides":
                decision.hints = hints
                decision.risk = decision.risk or risk
                trace.final = decision
                return decision, trace
            if first is None:
                first = decision
                if self.combining != "deny-overrides":
                    break
        final = first or Decision(ASK, "no decider had an opinion", "engine")
        final.hints = hints + list(final.hints or [])
        final.risk = final.risk or risk
        trace.final = final
        return final, trace


def default_chain(*, project_root: str = "", org_policy: dict | None = None,
                  org_policy_path: str | None = None, extra: list | None = None) -> list:
    """The standard chain (design §9.2). ``extra`` deciders are placed before
    the mode default so a site's Python decider can take part."""
    chain = [HardBlockDecider(), OrgPolicyDecider(org_policy, org_policy_path), RulesDecider("deny"),
             RiskDecider(project_root), PlanPreapprovalDecider(), RulesDecider("ask"),
             RulesDecider("allow"), LessonsDecider()]
    chain.extend(extra or [])
    chain.append(ModeDecider())
    return chain


def load_entry_point_deciders() -> list:
    """Python deciders registered by other packages under ``itailor.policy.deciders``."""
    found = []
    try:
        from importlib.metadata import entry_points
        for entry in entry_points(group="itailor.policy.deciders"):
            try:
                factory = entry.load()
                found.append(factory() if callable(factory) else factory)
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return found


PROFILES: dict[str, dict] = {
    "desktop": {"mode": "default", "sandbox": "writes", "ask_at": "high"},
    "shared-server": {"mode": "default", "sandbox": "strict", "ask_at": "moderate",
                      "forbidNetworkTools": False},
    "ci": {"mode": "default", "sandbox": "strict", "ask_at": "high", "headless": True},
    "classroom": {"mode": "acceptEdits", "sandbox": "strict", "ask_at": "moderate"},
}


def _unused(_: Callable) -> None:  # keeps Callable imported for type readers
    return None
