# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
The JSON-lines transcript of a run: every event, credentials redacted,
appended as it happens so a crash loses nothing already recorded.
"""

from __future__ import annotations

import json
import os
import threading
import time

from .events import Event, redact


class Transcript:
    def __init__(self, path: str, metadata: dict | None = None) -> None:
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.created = time.time()
        self._write({"type": "transcript_start", "ts": self.created, "schemaVersion": "1.0",
                     "metadata": redact(metadata or {})})

    def _write(self, record: dict) -> None:
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def record(self, event: Event) -> None:
        self._write(event.to_dict())

    def note(self, type: str, **data) -> None:
        self._write({"type": type, "ts": time.time(), **redact(data)})

    @staticmethod
    def read(path: str) -> list[dict]:
        out = []
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line:
                        try:
                            out.append(json.loads(line))
                        except Exception:  # noqa: BLE001
                            continue
        except OSError:
            pass
        return out
