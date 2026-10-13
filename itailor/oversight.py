# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
Human oversight: two different questions through one pluggable interface.

* **permission** - "may I do this?" Answered ``allow`` (once), ``always``
  (this kind, this session) or ``deny``. No answer within the timeout is a
  denial: an unattended run never authorises anything by timing out.
* **consultation** - "which should I do?" Answered with free text or one of
  the offered options, or ``None`` when nobody answers.

Adapters: ``ConsoleOversight`` (a terminal prompt), ``CallbackOversight``
(two functions), ``QueueOversight`` (a thread-safe queue a web UI resolves,
as DAYA's permission broker), ``AutoDeny`` (headless). There is deliberately
no ``AutoAllow`` for consultations; for permissions, the
``bypassPermissions`` mode exists and is loud.
"""

from __future__ import annotations

import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Callable, Protocol

from .events import CancelToken

ALLOW, ALWAYS, DENY = "allow", "always", "deny"
VALID_DECISIONS = (ALLOW, ALWAYS, DENY)


@dataclass
class PermissionRequest:
    kind: str
    tool: str = ""
    summary: str = ""
    detail: str = ""
    command: str = ""
    args: dict = field(default_factory=dict)
    risk: dict | None = None
    hints: list = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    created: float = field(default_factory=time.time)
    request_type: str = "permission"

    def payload(self) -> dict:
        data = asdict(self)
        data["requestId"] = self.id
        data["requestType"] = data.pop("request_type")
        return data


@dataclass
class ConsultRequest:
    question: str
    options: list = field(default_factory=list)
    why: str = ""
    trigger: str = ""
    context: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    created: float = field(default_factory=time.time)
    request_type: str = "consult"

    def payload(self) -> dict:
        data = asdict(self)
        data["requestId"] = self.id
        data["requestType"] = data.pop("request_type")
        return data


class Oversight(Protocol):
    def ask_permission(self, request: PermissionRequest, *, timeout: float = 300.0,
                       cancel: CancelToken | None = None) -> str: ...

    def consult(self, request: ConsultRequest, *, timeout: float = 600.0,
                cancel: CancelToken | None = None) -> str | None: ...


class AutoDeny:
    """Headless: every permission question is a denial, every consultation unanswered.
    The run continues under stated assumptions and the report lists what was skipped."""

    name = "auto-deny"

    def ask_permission(self, request: PermissionRequest, *, timeout: float = 300.0,
                       cancel: CancelToken | None = None) -> str:
        return DENY

    def consult(self, request: ConsultRequest, *, timeout: float = 600.0,
                cancel: CancelToken | None = None) -> str | None:
        return None


class CallbackOversight:
    def __init__(self, permission: Callable[[PermissionRequest], str] | None = None,
                 consult: Callable[[ConsultRequest], str | None] | None = None) -> None:
        self._permission = permission
        self._consult = consult
        self.name = "callback"

    def ask_permission(self, request: PermissionRequest, *, timeout: float = 300.0,
                       cancel: CancelToken | None = None) -> str:
        if not self._permission:
            return DENY
        try:
            answer = str(self._permission(request) or DENY)
        except Exception:  # noqa: BLE001
            return DENY
        return answer if answer in VALID_DECISIONS else DENY

    def consult(self, request: ConsultRequest, *, timeout: float = 600.0,
                cancel: CancelToken | None = None) -> str | None:
        if not self._consult:
            return None
        try:
            return self._consult(request)
        except Exception:  # noqa: BLE001
            return None


class ConsoleOversight:
    """A terminal prompt. ``input()`` cannot be interrupted, so the timeout is
    best-effort: the prompt says how long the run will wait."""

    name = "console"

    def __init__(self, stream=None, reader: Callable[[str], str] | None = None) -> None:
        self.stream = stream or sys.stdout
        self.reader = reader or input

    def ask_permission(self, request: PermissionRequest, *, timeout: float = 300.0,
                       cancel: CancelToken | None = None) -> str:
        print(f"\n[iTailor] {request.summary}", file=self.stream)
        if request.detail:
            print(f"  {request.detail}", file=self.stream)
        if request.command:
            print(f"  command: {request.command}", file=self.stream)
        if request.risk:
            print(f"  risk: {request.risk.get('level')} (score {request.risk.get('score')})", file=self.stream)
        for hint in request.hints or []:
            print(f"  note: {hint}", file=self.stream)
        try:
            answer = self.reader(f"  allow once [y] / always this kind [a] / deny [n] (deny after {int(timeout)}s): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return DENY
        return {"y": ALLOW, "yes": ALLOW, "allow": ALLOW, "a": ALWAYS, "always": ALWAYS}.get(answer, DENY)

    def consult(self, request: ConsultRequest, *, timeout: float = 600.0,
                cancel: CancelToken | None = None) -> str | None:
        print(f"\n[iTailor needs your decision] {request.question}", file=self.stream)
        if request.why:
            print(f"  why: {request.why}", file=self.stream)
        for index, option in enumerate(request.options or [], 1):
            print(f"  {index}. {option}", file=self.stream)
        try:
            answer = self.reader("  your answer (number or text, empty = no answer): ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not answer:
            return None
        if answer.isdigit() and request.options and 1 <= int(answer) <= len(request.options):
            return str(request.options[int(answer) - 1])
        return answer


class QueueOversight:
    """Questions are published through ``on_request(payload)`` and answered
    later by ``resolve(request_id, answer)`` from another thread (a web
    handler). The asking thread blocks until then, the timeout, or cancel."""

    name = "queue"

    def __init__(self, on_request: Callable[[dict], None] | None = None) -> None:
        self.on_request = on_request
        self._pending: dict[str, dict] = {}
        self._lock = threading.RLock()

    def pending(self) -> list[dict]:
        with self._lock:
            return [dict(entry["payload"]) for entry in self._pending.values()]

    def resolve(self, request_id: str, answer: str | None) -> bool:
        with self._lock:
            entry = self._pending.get(request_id)
            if not entry:
                return False
            entry["answer"] = answer
            entry["event"].set()
            return True

    def _wait(self, request, timeout: float, cancel: CancelToken | None):
        event = threading.Event()
        entry = {"payload": request.payload(), "event": event, "answer": None}
        with self._lock:
            self._pending[request.id] = entry
        try:
            if self.on_request:
                self.on_request(entry["payload"])
            deadline = time.monotonic() + max(1.0, float(timeout))
            while True:
                if cancel is not None and cancel.is_cancelled:
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                if event.wait(min(0.25, remaining)):
                    return entry["answer"]
        finally:
            with self._lock:
                self._pending.pop(request.id, None)

    def ask_permission(self, request: PermissionRequest, *, timeout: float = 300.0,
                       cancel: CancelToken | None = None) -> str:
        answer = self._wait(request, timeout, cancel)
        return answer if answer in VALID_DECISIONS else DENY

    def consult(self, request: ConsultRequest, *, timeout: float = 600.0,
                cancel: CancelToken | None = None) -> str | None:
        answer = self._wait(request, timeout, cancel)
        return str(answer) if answer else None
