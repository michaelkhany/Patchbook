# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
The gate: one function every consequential action passes through.

It asks the policy engine first (deterministic: hard blocks, organisation
policy, rules, risk, plan pre-approval, lessons as hints, mode). Only an
``ask`` verdict reaches the human, through the oversight adapter, with the
exact command, the risk assessment and any lesson hints. Standing ``always``
grants are per session and per tool class; a refusal is remembered for the
run so a retry loop cannot nag; a timeout is a denial. Every decision is
emitted as an event and recorded as a lesson.
"""

from __future__ import annotations

from typing import Callable

from .events import CancelToken
from .lessons import LessonStore
from .oversight import ALLOW, ALWAYS, DENY, Oversight, PermissionRequest
from .policy.decisions import ALLOW as P_ALLOW, ALLOW_WITH, ASK, DENY as P_DENY, Action, Context, Decision
from .policy.engine import PolicyEngine, default_chain


class Gate:
    def __init__(self, *, engine: PolicyEngine | None = None, mode: str = "default", rules: dict | None = None,
                 oversight: Oversight | None = None, timeout: float = 300.0, cancel: CancelToken | None = None,
                 emit: Callable | None = None, lessons: LessonStore | None = None, project_root: str = "",
                 profile: str = "desktop", machine: dict | None = None) -> None:
        self.engine = engine or PolicyEngine(default_chain(project_root=project_root))
        self.mode = mode
        self.rules = rules or {"allow": [], "deny": [], "ask": []}
        self.oversight = oversight
        self.timeout = timeout
        self.cancel = cancel
        self.emit = emit
        self.lessons = lessons
        self.project_root = project_root
        self.profile = profile
        self.machine = machine or {}
        self.grants: set[str] = set()
        self.refused: set[str] = set()
        self.plan_approved = False
        self.approved_signatures: set[str] = set()
        self.decisions: list[dict] = []

    # -- helpers -------------------------------------------------------------
    def _say(self, type: str, message: str = "", **data) -> None:
        if self.emit:
            try:
                self.emit(type, message, **data)
            except Exception:  # noqa: BLE001
                pass

    def _record(self, action: Action, decision: str, source: str, reason: str = "", trace: dict | None = None) -> None:
        entry = {"tool": action.tool, "gate": action.gate, "command": action.command or action.subject,
                 "decision": decision, "source": source, "reason": reason}
        self.decisions.append(entry)
        self._say("decision", f"{action.tool or action.gate}: {decision} ({source})", **entry, trace=trace or {})

    def _situation(self, action: Action) -> dict:
        return {"tool": action.tool, "gate": action.gate, "subject": action.subject[:200], "command": action.command[:200],
                "klass": action.klass, "os": __import__("platform").system().lower()}

    def _context(self, action: Action) -> Context:
        lessons: list[dict] = []
        if self.lessons is not None:
            try:
                for lesson, _score in self.lessons.retrieve(self._situation(action), kind="permission", k=3):
                    lessons.append(lesson.to_dict())
            except Exception:  # noqa: BLE001
                lessons = []
        return Context(mode=self.mode, rules=self.rules, plan_approved=self.plan_approved,
                       approved_signatures=self.approved_signatures, lessons=lessons, profile=self.profile,
                       machine=self.machine)

    # -- the gate ------------------------------------------------------------
    def __call__(self, action: Action) -> Decision:
        context = self._context(action)
        decision, trace = self.engine.evaluate(action, context)
        if decision.verdict == P_DENY:
            self._record(action, DENY, decision.source, decision.reason, trace.to_dict())
            return decision
        if decision.verdict in (P_ALLOW, ALLOW_WITH):
            self._record(action, ALLOW, decision.source, decision.reason, trace.to_dict())
            return decision
        # ask (or defer, handled as ask for now)
        if action.klass in self.grants and action.klass not in ("human", "consult"):
            self._record(action, ALWAYS, "standing grant", "always allowed this session", trace.to_dict())
            return Decision(P_ALLOW, "always allowed this session", "standing-grant", risk=decision.risk)
        signature = action.signature
        if signature in self.refused:
            self._record(action, DENY, "refused earlier", "you declined this earlier in the run", trace.to_dict())
            return Decision(P_DENY, "you declined this earlier in the run", "run-refusal", risk=decision.risk)
        if self.oversight is None:
            self.refused.add(signature)
            self._record(action, DENY, "no one to ask", decision.reason, trace.to_dict())
            return Decision(P_DENY, "no one to ask (headless run)", "headless", risk=decision.risk)
        request = PermissionRequest(kind=action.klass, tool=action.tool, summary=action.summary or f"{action.tool}?",
                                    detail=action.detail, command=action.command or action.subject, args=action.args,
                                    risk=decision.risk, hints=list(decision.hints or []))
        self._say("permission_request", request.summary, **request.payload())
        try:
            answer = self.oversight.ask_permission(request, timeout=self.timeout, cancel=self.cancel)
        except Exception:  # noqa: BLE001
            answer = DENY
        if answer == ALWAYS:
            self.grants.add(action.klass)
        if answer not in (ALLOW, ALWAYS):
            answer = DENY
            self.refused.add(signature)
        self._record(action, answer, "user" if answer != DENY else "user or timeout", decision.reason, trace.to_dict())
        if self.lessons is not None:
            try:
                self.lessons.record_permission(self._situation(action), answer,
                                               rationale=f"risk {decision.risk.get('level')}" if decision.risk else "")
            except Exception:  # noqa: BLE001
                pass
        if answer == DENY:
            return Decision(P_DENY, "declined by the user", "user", risk=decision.risk)
        return Decision(P_ALLOW, "allowed once" if answer == ALLOW else "always allowed", "user", risk=decision.risk)

    def approve_plan(self, signatures: set[str]) -> None:
        self.plan_approved = True
        self.approved_signatures |= set(signatures)
