# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
A content-hash memo for tool results that are pure given their inputs
(a fetched page, the environment manifest, a script whose code and inputs
hash the same). Lives under a run or project directory; JSON on disk.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any


class ContentCache:
    def __init__(self, directory: str, ttl_seconds: float | None = None) -> None:
        self.directory = directory
        self.ttl = ttl_seconds
        os.makedirs(directory, exist_ok=True)

    @staticmethod
    def key(*parts: Any) -> str:
        raw = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _path(self, key: str) -> str:
        return os.path.join(self.directory, key + ".json")

    def get(self, key: str) -> Any:
        path = self._path(key)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                entry = json.load(handle)
        except Exception:  # noqa: BLE001
            return None
        if self.ttl is not None and time.time() - float(entry.get("ts", 0)) > self.ttl:
            return None
        return entry.get("value")

    def set(self, key: str, value: Any) -> None:
        try:
            with open(self._path(key), "w", encoding="utf-8") as handle:
                json.dump({"ts": time.time(), "value": value}, handle, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            pass

    def memo(self, parts: tuple, compute):
        key = self.key(*parts)
        hit = self.get(key)
        if hit is not None:
            return hit, True
        value = compute()
        self.set(key, value)
        return value, False
