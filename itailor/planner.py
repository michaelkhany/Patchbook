# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
Plans: the model drafts, a deterministic validator judges (the LLM+P
pattern, Liu et al. 2023; the plan shape is a hierarchical task network,
Erol, Hendler & Nau 1994: steps with inputs (preconditions), outputs
(effects), dependencies and an acceptance check).

The validator checks what a planner must get right before anything runs:
unique ids, dependencies that exist, no cycles (Kahn's topological sort),
an acceptance check on every step, inputs that are produced by a
dependency or already exist in the project, languages that can run here,
and the step budget. Violations go back to the model verbatim; a plan that
still fails after ``max_tries`` is replaced by a single-step plan so the run
can proceed under a stated limitation.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict

from .checks import CHECK_KINDS
from .jsonschema_lite import extract_json, validate as validate_json

STEP_KINDS = ("code", "command", "tool", "checkpoint")

PLAN_SCHEMA = {
    "type": "object",
    "required": ["steps"],
    "properties": {
        "restatement": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "steps": {"type": "array", "minItems": 1, "items": {
            "type": "object",
            "required": ["id", "title", "kind", "instruction", "check"],
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "title": {"type": "string", "minLength": 1},
                "kind": {"type": "string", "enum": list(STEP_KINDS)},
                "instruction": {"type": "string", "minLength": 1},
                "language": {"type": "string"},
                "inputs": {"type": "array", "items": {"type": "string"}},
                "outputs": {"type": "array", "items": {"type": "string"}},
                "depends_on": {"type": "array", "items": {"type": "string"}},
                "check": {"type": "object", "required": ["type"], "properties": {"type": {"type": "string"}}},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
        }},
    },
}

UNDERSTAND_SCHEMA = {
    "type": "object",
    "required": ["restatement"],
    "properties": {
        "restatement": {"type": "string"},
        "unknowns": {"type": "array", "items": {"type": "object", "required": ["question", "materiality"], "properties": {
            "question": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}},
            "materiality": {"type": "string", "enum": ["low", "medium", "high"]}}}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
}


@dataclass
class Step:
    id: str
    title: str
    kind: str = "code"
    instruction: str = ""
    language: str = ""
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    depends_on: list = field(default_factory=list)
    check: dict = field(default_factory=lambda: {"type": "exit_zero"})
    tags: list = field(default_factory=list)
    status: str = "pending"          # pending | running | done | failed | skipped
    attempts: int = 0
    summary: str = ""
    check_results: list = field(default_factory=list)
    artifacts: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Step":
        known = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        known.setdefault("id", str(data.get("id") or ""))
        known.setdefault("title", str(data.get("title") or known["id"]))
        return cls(**known)


@dataclass
class Plan:
    goal: str
    restatement: str = ""
    assumptions: list = field(default_factory=list)
    steps: list = field(default_factory=list)
    revision: int = 0
    notes: list = field(default_factory=list)
    created: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def to_dict(self) -> dict:
        return {"goal": self.goal, "restatement": self.restatement, "assumptions": list(self.assumptions),
                "steps": [s.to_dict() for s in self.steps], "revision": self.revision, "notes": list(self.notes),
                "created": self.created}

    @classmethod
    def from_dict(cls, data: dict, goal: str = "") -> "Plan":
        return cls(goal=goal or str(data.get("goal") or ""), restatement=str(data.get("restatement") or ""),
                   assumptions=list(data.get("assumptions") or []),
                   steps=[Step.from_dict(s) for s in (data.get("steps") or [])],
                   revision=int(data.get("revision") or 0), notes=list(data.get("notes") or []),
                   created=str(data.get("created") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))

    def step(self, step_id: str) -> Step | None:
        for s in self.steps:
            if s.id == step_id:
                return s
        return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def topological_order(steps: list[Step]) -> tuple[list[Step], list[str]]:
    """Kahn's algorithm. Returns (ordered steps, ids left in a cycle)."""
    by_id = {s.id: s for s in steps}
    indegree = {s.id: 0 for s in steps}
    for s in steps:
        for dep in s.depends_on:
            if dep in by_id:
                indegree[s.id] += 1
    ready = [s for s in steps if indegree[s.id] == 0]
    ordered: list[Step] = []
    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for s in steps:
            if current.id in s.depends_on and s.id in indegree:
                indegree[s.id] -= 1
                if indegree[s.id] == 0 and s not in ordered and s not in ready:
                    ready.append(s)
    cyclic = [sid for sid, deg in indegree.items() if deg > 0]
    return ordered, cyclic


def validate(plan: Plan, *, project: str = "", available_languages: list | None = None,
             max_steps: int = 20) -> list[str]:
    violations: list[str] = []
    steps = plan.steps
    if not steps:
        return ["the plan has no steps"]
    if len(steps) > max_steps:
        violations.append(f"{len(steps)} steps exceed the budget of {max_steps}; merge or drop steps")
    ids = [s.id for s in steps]
    for sid in {i for i in ids if ids.count(i) > 1}:
        violations.append(f"step id '{sid}' is used more than once")
    known = set(ids)
    for s in steps:
        if s.kind not in STEP_KINDS:
            violations.append(f"step {s.id}: kind '{s.kind}' is not one of {STEP_KINDS}")
        for dep in s.depends_on:
            if dep not in known:
                violations.append(f"step {s.id}: depends_on '{dep}' which does not exist")
            if dep == s.id:
                violations.append(f"step {s.id} depends on itself")
        check_type = str((s.check or {}).get("type") or "")
        if s.kind == "checkpoint":
            if check_type not in ("human", "exit_zero"):
                violations.append(f"step {s.id}: a checkpoint's check must be {{'type': 'human'}}")
        elif check_type not in CHECK_KINDS:
            violations.append(f"step {s.id}: check type '{check_type}' is not one of {CHECK_KINDS}; every step needs a checkable outcome")
        elif check_type in ("file_exists", "csv_rows", "json_valid") and not (s.check or {}).get("path"):
            violations.append(f"step {s.id}: check '{check_type}' needs a 'path'")
        elif check_type in ("stdout_matches", "stdout_not_matches") and not (s.check or {}).get("pattern"):
            violations.append(f"step {s.id}: check '{check_type}' needs a 'pattern'")
        elif check_type == "command_exit_zero" and not (s.check or {}).get("command"):
            violations.append(f"step {s.id}: check 'command_exit_zero' needs a 'command'")
        if s.language and available_languages is not None and s.language.lower() not in available_languages:
            violations.append(f"step {s.id}: language '{s.language}' cannot run on this machine (available: {', '.join(available_languages)})")
        if not s.instruction.strip():
            violations.append(f"step {s.id}: instruction is empty")
    ordered, cyclic = topological_order(steps)
    if cyclic:
        violations.append(f"dependency cycle among steps {cyclic}")
        return violations
    produced: set[str] = set()
    for s in ordered:
        deps_outputs = set()
        for dep in s.depends_on:
            d = plan.step(dep)
            if d:
                deps_outputs.update(d.outputs)
        for item in s.inputs:
            if item in deps_outputs or item in produced:
                continue
            if project and os.path.exists(os.path.join(project, item)):
                continue
            if item.startswith(("http://", "https://")):
                continue
            violations.append(f"step {s.id}: input '{item}' is neither produced by an earlier step nor present in the project")
        produced.update(s.outputs)
    return violations


def single_step_plan(goal: str, check: dict | None = None, note: str = "") -> Plan:
    plan = Plan(goal=goal, restatement=goal, steps=[Step(id="s1", title="Do the task", kind="code", instruction=goal,
                                                        check=check or {"type": "exit_zero"})])
    if note:
        plan.notes.append(note)
    return plan


# ---------------------------------------------------------------------------
# Drafting with a model
# ---------------------------------------------------------------------------
PLAN_SYSTEM = """You are the planning half of iTailor. Decompose the goal into an ordered plan of steps that an autonomous agent will execute one by one with tools (reading and editing files, running scripts in the languages listed, running commands, installing packages with permission, searching the web, finding installed programs and applications).

Reply with ONE JSON object and nothing else:
{"restatement": "...", "assumptions": ["..."],
 "steps": [{"id": "s1", "title": "...", "kind": "code|command|tool|checkpoint", "instruction": "what to do, concretely",
            "language": "python" (optional), "inputs": ["relative/path or output name"], "outputs": ["relative/path"],
            "depends_on": ["s0"], "check": {"type": "...", ...}, "tags": ["data", "plot"]}]}

Rules:
- Every step needs an acceptance check that a program can evaluate after the step. Check types: file_exists {path, "fresh": true} (fresh = the file must be written during this step, not left over from earlier), csv_rows {path, min_rows, columns}, json_valid {path, required_keys}, stdout_matches {pattern}, stdout_not_matches {pattern}, exit_zero {}, command_exit_zero {command}. A checkpoint step (a human reviews intermediate results) uses {"type": "human"}. For a step that produces a file, use file_exists with "fresh": true.
- Prefer file_exists / csv_rows / json_valid checks on named output files over exit_zero: an exit code is necessary, never sufficient.
- inputs must be files that exist in the project or outputs of an earlier step (name them identically). outputs are the files the step will leave behind.
- Use only languages that can run here. Do not invent paths. Fewer, substantial steps beat many trivial ones; stay within the step budget.
- Do not add steps for things the agent does automatically (installing a missing package, reading the error, retrying)."""

UNDERSTAND_SYSTEM = """You are the understanding half of iTailor. Before planning, restate the goal in one sentence, list the unknowns that would change the work if answered differently, and the assumptions you would make if nobody answers.

Reply with ONE JSON object and nothing else:
{"restatement": "...", "unknowns": [{"question": "...", "options": ["..."], "materiality": "low|medium|high"}],
 "assumptions": ["..."], "tags": ["short", "topic", "tags"]}

materiality: high = the whole approach changes; medium = a step changes; low = cosmetic. Most goals have zero or one high-materiality unknown. Do not ask about things the environment description already answers."""


def _ask_json(client, system: str, user: str, schema: dict, *, max_tries: int = 3, cancel=None, emit=None,
              temperature: float = 0.1, max_tokens: int = 2500) -> tuple[dict | None, str]:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last_error = ""
    for attempt in range(1, max_tries + 1):
        reply = client.complete(messages, cancel=cancel, temperature=temperature, max_tokens=max_tokens)
        if not reply.ok:
            return None, reply.error
        try:
            data = extract_json(reply.text)
        except ValueError as exc:
            last_error = str(exc)
            messages += [{"role": "assistant", "content": reply.text[:3000]},
                         {"role": "user", "content": "Reply with ONE valid JSON object only, no prose."}]
            continue
        errors = validate_json(data, schema)
        if not errors:
            return data, ""
        last_error = "; ".join(errors[:8])
        if emit:
            emit("think", f"The plan JSON had {len(errors)} schema problem(s); asking again…")
        messages += [{"role": "assistant", "content": reply.text[:3000]},
                     {"role": "user", "content": "The JSON does not match the required shape:\n- " + "\n- ".join(errors[:12])
                      + "\nReply with the corrected JSON object only."}]
    return None, last_error or "no valid JSON after retries"


def understand(client, goal: str, *, env_summary: str = "", context: str = "", cancel=None, emit=None) -> dict:
    user = f"GOAL:\n{goal}\n\nENVIRONMENT:\n{env_summary}\n" + (f"\nPROJECT CONTEXT:\n{context}\n" if context else "")
    data, error = _ask_json(client, UNDERSTAND_SYSTEM, user, UNDERSTAND_SCHEMA, cancel=cancel, emit=emit, max_tokens=1200)
    if not data:
        return {"restatement": goal, "unknowns": [], "assumptions": [], "tags": [], "error": error}
    data.setdefault("unknowns", [])
    data.setdefault("assumptions", [])
    data.setdefault("tags", [])
    return data


def draft(client, goal: str, *, project: str = "", env_summary: str = "", context: str = "",
          available_languages: list | None = None, max_steps: int = 20, clarifications: list | None = None,
          max_tries: int = 3, cancel=None, emit=None, previous: Plan | None = None, evidence: str = "") -> tuple[Plan | None, str]:
    """Draft (or revise, when ``previous`` and ``evidence`` are given) a plan and validate it."""
    user = (f"GOAL:\n{goal}\n\nENVIRONMENT:\n{env_summary}\n"
            f"Languages that can run here: {', '.join(available_languages or [])}\nStep budget: {max_steps}\n")
    if context:
        user += f"\nPROJECT CONTEXT:\n{context}\n"
    if clarifications:
        user += "\nCLARIFICATIONS FROM THE USER:\n- " + "\n- ".join(clarifications) + "\n"
    if previous is not None:
        done = [s for s in previous.steps if s.status == "done"]
        user += ("\nTHIS IS A REVISION. Steps already completed (keep their ids and mark nothing about them; do not repeat them):\n"
                 + "\n".join(f"- {s.id}: {s.title} -> outputs {s.outputs}" for s in done)
                 + f"\n\nWHAT WENT WRONG:\n{evidence}\n\nPlan only the remaining work. Completed steps' outputs are available as inputs.\n")
    messages_user = user
    violations_text = ""
    plan: Plan | None = None
    for attempt in range(1, max_tries + 1):
        text = messages_user + (f"\nYOUR PREVIOUS PLAN WAS REJECTED FOR THESE REASONS - fix all of them:\n- {violations_text}\n" if violations_text else "")
        data, error = _ask_json(client, PLAN_SYSTEM, text, PLAN_SCHEMA, cancel=cancel, emit=emit)
        if not data:
            return None, error
        plan = Plan.from_dict(data, goal=goal)
        if previous is not None:
            plan.revision = previous.revision + 1
            kept = [s for s in previous.steps if s.status == "done"]
            kept_ids = {s.id for s in kept}
            plan.steps = kept + [s for s in plan.steps if s.id not in kept_ids]
        violations = validate(plan, project=project, available_languages=available_languages, max_steps=max_steps)
        if not violations:
            return plan, ""
        violations_text = "\n- ".join(violations)
        if emit:
            emit("think", f"Plan draft {attempt} rejected by the validator ({len(violations)} problem(s)); asking for a fix…")
    return plan, f"the plan still had violations after {max_tries} tries: {violations_text}"


def to_markdown(plan: Plan) -> str:
    lines = [f"# Plan (revision {plan.revision})", "", f"**Goal:** {plan.goal}", ""]
    if plan.restatement:
        lines += [f"**Understood as:** {plan.restatement}", ""]
    if plan.assumptions:
        lines += ["**Assumptions:**"] + [f"- {a}" for a in plan.assumptions] + [""]
    lines += ["| # | Step | Kind | Status | Check | Depends on |", "| --- | --- | --- | --- | --- | --- |"]
    for s in plan.steps:
        check = s.check.get("type", "") + (" " + str(s.check.get("path") or s.check.get("pattern") or s.check.get("command") or "")).rstrip()
        lines.append(f"| {s.id} | {s.title} | {s.kind} | {s.status} | {check} | {', '.join(s.depends_on) or '-'} |")
    lines.append("")
    for s in plan.steps:
        lines += [f"## {s.id} - {s.title}", "", s.instruction, ""]
        if s.inputs:
            lines.append(f"- inputs: {', '.join(s.inputs)}")
        if s.outputs:
            lines.append(f"- outputs: {', '.join(s.outputs)}")
        lines.append(f"- check: `{json.dumps(s.check)}`")
        if s.summary:
            lines.append(f"- result: {s.summary}")
        lines.append("")
    if plan.notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in plan.notes]
    return "\n".join(lines)
