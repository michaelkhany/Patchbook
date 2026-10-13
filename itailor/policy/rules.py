# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
Declarative rules in Claude Code's syntax: ``Tool`` or ``Tool(pattern)``,
where the pattern is a glob (``Edit(src/**)``), a prefix (``Shell(git:*)``)
or ``*``. ``*`` as the tool name matches every tool.
"""

from __future__ import annotations

import re

from .decisions import subject_of

_RULE_RE = re.compile(r"^\s*([A-Za-z_*]+)\s*(?:\((.*)\))?\s*$")


def glob_to_regex(pattern: str) -> re.Pattern:
    out = ""
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                out += ".*"
                i += 1
                if i + 1 < len(pattern) and pattern[i + 1] == "/":
                    i += 1
            else:
                out += r"[^/\\]*"
        elif ch == "?":
            out += "."
        elif ch in "\\^$+.()|{}[]":
            out += "\\" + ch
        else:
            out += ch
        i += 1
    return re.compile("^" + out + "$", re.IGNORECASE)


def parse_rule(rule: str) -> dict | None:
    match = _RULE_RE.match(str(rule or ""))
    if not match:
        return None
    pattern = match.group(2)
    return {"tool": match.group(1), "pattern": pattern.strip() if pattern is not None else None, "text": rule}


def rule_matches(rule, tool: str, args: dict | None) -> bool:
    parsed = parse_rule(rule) if isinstance(rule, str) else rule
    if not parsed:
        return False
    if parsed["tool"] != tool and parsed["tool"] != "*":
        return False
    pattern = parsed["pattern"]
    if pattern is None or pattern == "" or pattern == "*":
        return True
    subject = subject_of(tool, args)
    if pattern.endswith(":*"):
        return subject.startswith(pattern[:-2])
    regex = glob_to_regex(pattern)
    return bool(regex.match(subject) or regex.match(subject.split("/")[-1]))


def first_match(rules, tool: str, args: dict | None):
    for rule in rules or []:
        if rule_matches(rule, tool, args):
            return rule
    return None
