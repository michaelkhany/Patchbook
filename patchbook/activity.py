# Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
The activity record of a project: what was used while its Patchbooks ran, for review later.

After every run Patchbook distils the run's event log into one record and appends
it to ``<project>/.patchbook/activity.jsonl``: when, which cell, which model and
effort, the approaches tried, every program and script that ran (with its
outcome), packages installed, permission decisions and who made them, files
produced, and how many warnings and errors were seen. iTailor's own transcripts
stay where they are (``.itailor/runs/``); this is the human-readable map on top.
"""

from __future__ import annotations

import json
import os
import re
import time

DIRNAME = ".patchbook"
FILENAME = "activity.jsonl"
ERROR_LINE = re.compile(r"\b(error|exception|traceback|fatal|failed)\b", re.IGNORECASE)
WARNING_LINE = re.compile(r"\bwarn(ing)?\b", re.IGNORECASE)


def path(project: str) -> str:
    return os.path.join(project, DIRNAME, FILENAME)


def describe_tool_call(event: dict) -> dict | None:
    """One started program, script, installation or application, from a tool_call event."""
    name = str(event.get("name") or "")
    args = event.get("args") if isinstance(event.get("args"), dict) else {}
    if name == "RunCode":
        return {"kind": "script", "what": f"{args.get('language') or 'script'} script" + (f" ({args.get('lines')} lines)" if args.get("lines") else "")}
    if name == "Shell":
        return {"kind": "command", "what": str(args.get("command") or event.get("message") or "command")[:200]}
    if name == "Install":
        packages = args.get("packages") or ([args.get("package")] if args.get("package") else [])
        return {"kind": "install", "what": f"{args.get('manager') or 'package manager'}: {', '.join(str(p) for p in packages) or '?'}"}
    if name == "OpenWith":
        return {"kind": "application", "what": str(args.get("app") or args.get("name") or event.get("message") or "application")[:200]}
    if name in ("WebSearch", "WebFetch"):
        return {"kind": "web", "what": str(args.get("query") or args.get("url") or name)[:200]}
    if name:
        return {"kind": "tool", "what": name + (": " + str(args.get("path") or args.get("pattern") or "")[:120] if args.get("path") or args.get("pattern") else "")}
    return None


def summarize(entry: dict, result: dict) -> dict:
    """Distil a finished run (the run manager's entry and the cell result) into one record."""
    log = list(entry.get("log") or [])
    programs: list[dict] = []
    open_programs: list[dict] = []
    decisions: list[dict] = []
    errors = warnings = 0
    for event in log:
        kind = event.get("type")
        if kind == "tool_call":
            described = describe_tool_call(event)
            if described:
                described.update({"at": event.get("ts"), "ok": None, "name": event.get("name")})
                programs.append(described)
                open_programs.append(described)
        elif kind == "tool_result":
            name = event.get("name")
            for program in reversed(open_programs):
                if program.get("name") == name or name is None:
                    program["ok"] = bool(event.get("ok")) if event.get("ok") is not None else None
                    program["summary"] = str(event.get("message") or "")[:200]
                    if event.get("ts") and program.get("at"):
                        program["seconds"] = round(float(event["ts"]) - float(program["at"]), 1)
                    open_programs.remove(program)
                    break
        elif kind == "observe":
            message = str(event.get("message") or "")
            if message.startswith("The script ran") or message.startswith("The script failed"):
                for program in reversed(open_programs):
                    if program.get("name") == "RunCode":
                        program["ok"] = message.startswith("The script ran")
                        program["summary"] = message[:200]
                        if event.get("ts") and program.get("at"):
                            program["seconds"] = round(float(event["ts"]) - float(program["at"]), 1)
                        open_programs.remove(program)
                        break
                if message.startswith("The script failed"):
                    errors += 1
        elif kind == "decision":
            decisions.append({"tool": event.get("tool"), "command": str(event.get("command") or event.get("summary") or "")[:160],
                              "decision": event.get("decision"), "source": event.get("source"), "reason": str(event.get("reason") or "")[:160]})
        elif kind == "error":
            errors += 1
        elif kind == "output":
            text = str(event.get("message") or "")
            if event.get("stream") == "stderr" or ERROR_LINE.search(text):
                errors += len([line for line in text.splitlines() if ERROR_LINE.search(line)])
            warnings += len([line for line in text.splitlines() if WARNING_LINE.search(line)])
    installs = [p["what"] for p in programs if p["kind"] == "install"]
    return {
        "id": entry.get("id"), "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(entry.get("started") or time.time())),
        "seconds": round((entry.get("finished") or time.time()) - (entry.get("started") or time.time()), 1),
        "patchbook": entry.get("patchbookId"), "cell": entry.get("cellIndex"), "task": str(entry.get("task") or "")[:200],
        "status": entry.get("status"), "model": entry.get("model") or ("demo-model" if entry.get("demo") else ""), "effort": entry.get("effort"),
        "approaches": [{"label": a.get("label"), "status": a.get("status")} for a in (entry.get("attempts") or [])],
        "programs": programs[:60], "installs": installs, "decisions": decisions[:40],
        "files": [f.get("path") for f in (result.get("files") or []) if isinstance(f, dict)][:40],
        "errors": errors, "warnings": warnings,
    }


def record(project: str, summary: dict) -> None:
    file = path(project)
    os.makedirs(os.path.dirname(file), exist_ok=True)
    with open(file, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, ensure_ascii=False, default=str) + "\n")


def load(project: str, limit: int = 100) -> list[dict]:
    file = path(project)
    if not os.path.isfile(file):
        return []
    records: list[dict] = []
    with open(file, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
    return list(reversed(records[-limit:]))
