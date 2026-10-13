# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
Tool calling for models WITHOUT native function calling.

Such a model is told to answer with exactly one ``<tool>`` block, which is
parsed here into the same ``{name, args}`` shape the native path produces,
and tool results go back as plain text. Three spellings are accepted:

    <tool name="Read">{"path": "src/app.py"}</tool>
    ```tool\n{"tool": "Read", "args": {...}}\n```
    {"tool": "Read", "args": {...}}            (a bare JSON line)
"""

from __future__ import annotations

import json
import re
import time

TOOL_BLOCK_RE = re.compile(r"<tool\s+name\s*=\s*[\"']([A-Za-z_][\w]*)[\"']\s*>\s*([\s\S]*?)\s*</tool>", re.I)
FENCED_TOOL_RE = re.compile(r"```tool[ \t]*\r?\n([\s\S]*?)```", re.I)
JSON_LINE_RE = re.compile(r"^\s*\{\s*\"tool\"\s*:\s*\"([A-Za-z_]\w*)\"[\s\S]*\}\s*$", re.M)


def parse_args(text: str) -> dict:
    body = str(text or "").strip()
    if not body:
        return {}
    cleaned = re.sub(r"^```(?:json)?\s*", "", body, flags=re.I)
    cleaned = re.sub(r"```\s*$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:  # noqa: BLE001
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else {}
            except Exception:  # noqa: BLE001
                pass
        return {"__parse_error": cleaned[:2000]}


def _call(name: str, args: dict) -> dict:
    return {"id": f"text_{int(time.time() * 1000)}", "name": str(name), "args": args}


def parse(text: str) -> dict:
    """Returns ``{"content": narration, "tool_calls": [{id, name, args}]}``."""
    s = str(text or "")
    match = TOOL_BLOCK_RE.search(s)
    if match:
        return {"content": s[: match.start()].strip(), "tool_calls": [_call(match.group(1), parse_args(match.group(2)))]}
    match = FENCED_TOOL_RE.search(s)
    if match:
        args = parse_args(match.group(1))
        name = args.get("tool") or args.get("name")
        if name:
            rest = {k: v for k, v in args.items() if k not in ("tool", "name")}
            inner = rest["args"] if isinstance(rest.get("args"), dict) else rest
            return {"content": s[: match.start()].strip(), "tool_calls": [_call(name, inner)]}
    match = JSON_LINE_RE.search(s)
    if match:
        args = parse_args(match.group(0))
        if args.get("tool"):
            inner = args["args"] if isinstance(args.get("args"), dict) else {k: v for k, v in args.items() if k != "tool"}
            return {"content": s[: match.start()].strip(), "tool_calls": [_call(args["tool"], inner)]}
    return {"content": s.strip(), "tool_calls": []}


def instructions(tools: list[dict]) -> str:
    """The protocol text appended to the system prompt in text mode. ``tools``
    are plain specs: ``{name, description, parameters}``."""
    lines = []
    for tool in tools:
        props = (tool.get("parameters") or {}).get("properties") or {}
        required = set((tool.get("parameters") or {}).get("required") or [])
        params = "; ".join(
            f"{k}{'' if k in required else '?'}: {v.get('type', 'any')}" + (f" - {v['description']}" if v.get("description") else "")
            for k, v in props.items())
        lines.append(f"- {tool['name']}: {tool.get('description', '')}\n    parameters: {params or '(none)'}")
    return "\n".join([
        "TOOL PROTOCOL (this model has no native function calling, so tools are called in text):",
        "To use a tool, reply with a short sentence of intent and then EXACTLY ONE block in this shape, and nothing after it:",
        '<tool name="Read">', '{"path": "src/app.py"}', "</tool>",
        "The arguments are a single JSON object. You will receive the result in the next message as <tool_result>.",
        "Call one tool per reply. When the task is complete, reply with plain text and NO tool block.",
        "", "AVAILABLE TOOLS:", *lines])


def format_result(name: str, result) -> str:
    body = result if isinstance(result, str) else json.dumps(result, indent=1, ensure_ascii=False, default=str)
    return f'<tool_result name="{name}">\n{body[:30000]}\n</tool_result>'
