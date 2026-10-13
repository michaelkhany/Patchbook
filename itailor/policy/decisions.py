# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
The vocabulary of the policy engine: what is being decided and what a decision is.

``itailor.policy`` imports nothing from the rest of iTailor, so it can be
published on its own if a second consumer appears (design §9).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Any

# Verdicts
ALLOW = "allow"
ALLOW_WITH = "allow_with"     # allow, with modifications the caller must apply
ASK = "ask"                   # a human must decide
DEFER = "defer"               # queue for a batched question
DENY = "deny"
ABSTAIN = "abstain"           # this decider has no opinion
VERDICTS = (ALLOW, ALLOW_WITH, ASK, DEFER, DENY, ABSTAIN)

# Gates (design §9.1)
GATES = ("tool", "install", "network", "write", "exec_app", "model", "plan", "step",
         "budget", "consult", "lesson")

# Permission modes (Claude Code / Patch Code)
MODES = ("default", "acceptEdits", "plan", "bypassPermissions")

# Tool classes: how consequential a tool is when no rule applies.
TOOL_CLASS = {
    "Read": "read", "Glob": "read", "Grep": "read", "ListDir": "read", "Diagnostics": "read",
    "WebSearch": "read", "WebFetch": "read", "KnowledgeGraph": "read", "EnvInfo": "read",
    "FindProgram": "read", "FindApp": "read", "ProjectState": "read",
    "Edit": "edit", "Write": "edit", "MultiEdit": "edit", "Patch": "edit",
    "Shell": "shell", "RunCode": "run", "Install": "install", "OpenWith": "system",
    "AskUser": "human",
}


@dataclass
class Action:
    """What is about to happen, described for deciders."""
    gate: str = "tool"
    tool: str = ""
    args: dict = field(default_factory=dict)
    klass: str = ""                 # read | edit | run | shell | install | system | human | plan | step ...
    summary: str = ""
    detail: str = ""
    command: str = ""
    read_only: bool = False
    destructive: bool = False
    paths: list = field(default_factory=list)      # filesystem paths the action touches
    egress: bool = False                           # sends data off the machine
    reversible: bool | None = None                 # None = infer from class
    cost: float = 0.0                              # money, if known
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.klass:
            self.klass = TOOL_CLASS.get(self.tool, "shell" if self.tool else self.gate)

    @property
    def subject(self) -> str:
        return subject_of(self.tool, self.args)

    @property
    def signature(self) -> str:
        """A stable identity for "the same action", for refusals and pre-approval."""
        raw = json.dumps({"g": self.gate, "t": self.tool, "c": self.command or self.subject},
                         sort_keys=True, default=str)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["signature"] = self.signature
        return data


@dataclass
class Context:
    """What the deciders may consult besides the action."""
    mode: str = "default"
    rules: dict = field(default_factory=lambda: {"allow": [], "deny": [], "ask": []})
    plan_approved: bool = False
    approved_signatures: set = field(default_factory=set)
    lessons: list = field(default_factory=list)       # retrieved lesson dicts for this situation
    profile: str = "desktop"
    run: dict = field(default_factory=dict)           # budgets spent, step index, …
    machine: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


@dataclass
class Decision:
    verdict: str
    reason: str = ""
    source: str = ""                      # which decider
    modifications: dict = field(default_factory=dict)
    question: str = ""
    options: list = field(default_factory=list)
    risk: dict | None = None
    hints: list = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.verdict in (ALLOW, ALLOW_WITH)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Trace:
    """Every decider's answer, in order, so a decision is explainable."""
    steps: list = field(default_factory=list)      # [{decider, verdict, reason}]
    final: Decision | None = None

    def add(self, decider: str, decision: Decision | None) -> None:
        self.steps.append({"decider": decider,
                           "verdict": decision.verdict if decision else ABSTAIN,
                           "reason": decision.reason if decision else ""})

    def to_dict(self) -> dict:
        return {"steps": list(self.steps), "final": self.final.to_dict() if self.final else None}


def subject_of(tool: str, args: dict | None) -> str:
    """The string a rule's pattern is matched against for a given tool call."""
    args = args or {}
    if tool == "Shell":
        return str(args.get("command") or "")
    if tool == "Install":
        return f"{args.get('manager') or ''} {' '.join(args.get('packages') or [])}".strip()
    if tool == "RunCode":
        return str(args.get("language") or "")
    if tool == "WebFetch":
        return str(args.get("url") or "")
    if tool == "WebSearch":
        return str(args.get("query") or "")
    if tool == "OpenWith":
        return f"{args.get('app') or ''} {args.get('path') or ''}".strip()
    return str(args.get("path") or args.get("file") or args.get("pattern") or "").replace("\\", "/")
