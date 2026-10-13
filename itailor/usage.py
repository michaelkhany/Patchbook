# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
Token accounting: only what the provider actually reports, and how many calls
reported nothing. A number a user might act on should not be a guess.
"""

from __future__ import annotations

import threading
import time


class UsageMeter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.calls = 0
        self.unreported_calls = 0
        self.by_model: dict[str, dict] = {}
        self.started = time.time()

    def record(self, usage: dict | None, model: str = "") -> None:
        with self._lock:
            self.calls += 1
            if not usage or not usage.get("reported", True):
                self.unreported_calls += 1
                return
            p = int(usage.get("promptTokens") or 0)
            c = int(usage.get("completionTokens") or 0)
            t = int(usage.get("totalTokens") or p + c)
            self.prompt_tokens += p
            self.completion_tokens += c
            self.total_tokens += t
            entry = self.by_model.setdefault(model or "?", {"calls": 0, "promptTokens": 0,
                                                            "completionTokens": 0, "totalTokens": 0})
            entry["calls"] += 1
            entry["promptTokens"] += p
            entry["completionTokens"] += c
            entry["totalTokens"] += t

    def snapshot(self) -> dict:
        with self._lock:
            return {"calls": self.calls, "unreportedCalls": self.unreported_calls,
                    "promptTokens": self.prompt_tokens, "completionTokens": self.completion_tokens,
                    "totalTokens": self.total_tokens, "byModel": {k: dict(v) for k, v in self.by_model.items()},
                    "elapsedSeconds": round(time.time() - self.started, 1)}
