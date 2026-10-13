# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
Events, cancellation and redaction - the plumbing every run shares.

One vocabulary of event types is used by every consumer (a callback, an
iterator, the JSON-lines transcript, a console renderer, DAYA's SSE broker):

    run_start · think · plan · step_start · tool_call · tool_result · observe ·
    permission_request · decision · consult_request · consult_answer · lesson ·
    output · usage · step_done · final · error · run_end

Cooperative cancellation is a ``CancelToken``: long operations call
``token.check()`` at safe points and the run unwinds with ``RunCancelled``.
Blocking calls that cannot be interrupted (``urllib``) are run in a daemon
thread by ``run_cancellable`` so the caller stays stoppable - the trick from
DAYA's ``agent_harness``.
"""

from __future__ import annotations

import contextvars
import json
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

EVENT_TYPES = (
    "run_start", "think", "plan", "step_start", "tool_call", "tool_result", "observe",
    "permission_request", "decision", "consult_request", "consult_answer", "lesson",
    "output", "usage", "step_done", "final", "error", "run_end", "delta", "route",
)


class RunCancelled(RuntimeError):
    """Raised at safe interruption points when a user stops a run."""


@dataclass
class Event:
    type: str
    message: str = ""
    data: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    seq: int = 0

    def to_dict(self) -> dict:
        return {"seq": self.seq, "ts": self.ts, "type": self.type,
                "message": self.message, **redact(self.data)}


class CancelToken:
    """A stop button. ``check()`` raises ``RunCancelled`` once it is pressed."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise RunCancelled("Run stopped by user.")

    def wait(self, seconds: float) -> bool:
        """Sleep, but wake early (and raise) when cancelled."""
        if self._event.wait(seconds):
            raise RunCancelled("Run stopped by user.")
        return False

    # threading.Event compatibility for code that only needs is_set()
    def is_set(self) -> bool:
        return self._event.is_set()


def run_cancellable(call: Callable[[], Any], cancel: CancelToken | None,
                    poll_seconds: float = 0.1) -> Any:
    """Run a blocking call while keeping the caller stoppable.

    Python cannot forcibly cancel a urllib call, so it lives in a daemon
    thread. Cancelling releases the caller immediately; the thread is left to
    finish or time out on its own without touching run state.
    """
    if cancel is None:
        return call()
    result: queue.Queue = queue.Queue(maxsize=1)

    def invoke() -> None:
        try:
            result.put((True, call()))
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller
            result.put((False, exc))

    context = contextvars.copy_context()
    threading.Thread(target=context.run, args=(invoke,), daemon=True).start()
    while True:
        cancel.check()
        try:
            ok, value = result.get(timeout=poll_seconds)
        except queue.Empty:
            continue
        if ok:
            return value
        raise value


class EventStream:
    """Fan-out of events to subscribers plus an iterator view.

    ``emit`` never raises because of a subscriber: a broken renderer must not
    kill the run it is rendering.
    """

    def __init__(self, on_event: Callable[[Event], None] | None = None, *, max_queued: int = 20000) -> None:
        self._subscribers: list[Callable[[Event], None]] = []
        # Bounded: a consumer that never drains the iterator must not grow memory forever.
        self._queue: queue.Queue = queue.Queue(maxsize=max_queued)
        self._lock = threading.Lock()
        self._seq = 0
        self._closed = False
        self.history: list[Event] = []
        self.keep_history = False
        if on_event:
            self._subscribers.append(on_event)

    def subscribe(self, fn: Callable[[Event], None]) -> None:
        with self._lock:
            self._subscribers.append(fn)

    def unsubscribe(self, fn: Callable[[Event], None]) -> None:
        with self._lock:
            self._subscribers = [s for s in self._subscribers if s is not fn]

    def emit(self, type: str, message: str = "", **data: Any) -> Event:
        with self._lock:
            self._seq += 1
            event = Event(type=type, message=str(message or ""), data=dict(data), seq=self._seq)
            if self.keep_history:
                self.history.append(event)
            subscribers = list(self._subscribers)
        for fn in subscribers:
            try:
                fn(event)
            except Exception:  # noqa: BLE001 - a consumer must never break the run
                pass
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            pass
        return event

    def drain(self) -> None:
        """Forget queued events nobody consumed (called at the start of a run)."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._queue.put(None)

    def __iter__(self) -> Iterator[Event]:
        return self.iter()

    def iter(self, heartbeat: float | None = None) -> Iterator[Event]:
        """Yield events until the stream is closed. With ``heartbeat`` a
        synthetic ``heartbeat`` event is yielded after that many quiet seconds."""
        while True:
            try:
                item = self._queue.get(timeout=heartbeat)
            except queue.Empty:
                yield Event(type="heartbeat")
                continue
            if item is None:
                return
            yield item


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------
SENSITIVE_KEYS = frozenset({
    "apikey", "api_key", "authorization", "password", "secret", "secret_key",
    "token", "access_token", "refresh_token", "openai_api_key", "itailor_api_key",
})


def redact(value: Any, key: str = "") -> Any:
    """Make a value JSON-safe while removing known credentials."""
    if str(key).lower() in SENSITIVE_KEYS:
        return "[redacted]"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:  # noqa: BLE001
        return str(value)


def clip(text: Any, limit: int) -> str:
    """Shorten a string for a prompt or an event, saying how much was cut."""
    s = str(text or "")
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n…[{len(s) - limit} more characters truncated]"


def tail(text: Any, limit: int) -> str:
    s = str(text or "")
    return s if len(s) <= limit else "…" + s[-limit:]
