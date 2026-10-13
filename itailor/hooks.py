# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
Hooks, in Claude Code's shape:

    "hooks": {
      "PreToolUse":  [{"matcher": "Shell|Write", "hooks": [{"type": "command", "command": "python check.py"}]}],
      "PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "ruff check ."}]}],
      "Stop":        [{"hooks": [{"type": "command", "command": "..."}]}]
    }

Each hook command receives a JSON payload on stdin. Exit code 2 blocks the
action (PreToolUse) and its stderr is fed back to the model; any other
non-zero exit is reported but does not block.
"""

from __future__ import annotations

import json
import re

from .events import CancelToken
from .tools import shell


def matches(matcher, tool_name: str) -> bool:
    if matcher in (None, "", "*"):
        return True
    text = str(matcher)
    if text == tool_name:
        return True
    try:
        return re.match(f"^(?:{text})$", tool_name) is not None
    except re.error:
        return tool_name in [s.strip() for s in text.split("|")]


def run(event: str, *, settings: dict, cwd: str, tool_name: str | None = None, payload: dict | None = None,
        cancel: CancelToken | None = None, timeout: float = 60.0) -> dict:
    entries = ((settings or {}).get("hooks") or {}).get(event) or []
    results = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
            continue
        if tool_name and not matches(entry.get("matcher"), tool_name):
            continue
        for hook in entry["hooks"]:
            if not isinstance(hook, dict) or hook.get("type") != "command" or not hook.get("command"):
                continue
            stdin = json.dumps({"event": event, "tool": tool_name, "cwd": cwd, **(payload or {})}, default=str)
            result = shell.run(hook["command"], cwd=cwd, timeout=float(hook.get("timeout") or timeout),
                               cancel=cancel, env=(settings or {}).get("env"), stdin=stdin)
            results.append({"command": hook["command"], "exitCode": result.get("exitCode"),
                            "stdout": result.get("stdout", ""), "stderr": result.get("stderr", "")})
            if result.get("exitCode") == 2:
                reason = (result.get("stderr") or result.get("stdout") or f"blocked by hook: {hook['command']}").strip()
                return {"block": True, "reason": reason, "results": results}
    return {"block": False, "reason": "", "results": results}
