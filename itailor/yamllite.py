# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
A small YAML writer and reader for the subset iTailor emits, so the project
knowledge graph can be a file a human reads and edits without the library
needing a dependency.

Subset: block mappings and sequences, scalars (strings, ints, floats,
booleans, null). Strings that could be misread are written as JSON-style
double-quoted strings, which is valid YAML and lets the reader use
``json.loads`` for them. Empty containers are written as ``[]`` / ``{}``.
Comments (``# …`` on their own line) are ignored by the reader.
"""

from __future__ import annotations

import json
import re
from typing import Any

_PLAIN_SAFE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ .\-/:@()+]*$")
_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "~", ""}
_NUMBER = re.compile(r"^-?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?$")


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    if (_PLAIN_SAFE.match(text) and text.lower() not in _RESERVED and not _NUMBER.match(text)
            and ": " not in text and " #" not in text and not text.endswith(":") and text == text.strip()):
        return text
    return json.dumps(text, ensure_ascii=False)


_KEY_SAFE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-/ ]*$")


def _key(key: Any) -> str:
    text = str(key)
    if _KEY_SAFE.match(text) and text.lower() not in _RESERVED and not _NUMBER.match(text) and text == text.strip():
        return text
    return json.dumps(text, ensure_ascii=False)


def dump(data: Any, indent: int = 2) -> str:
    lines: list[str] = []
    _emit(data, 0, lines, indent)
    return "\n".join(lines) + "\n"


def _emit(value: Any, level: int, lines: list, indent: int, prefix: str = "") -> None:
    pad = " " * level
    if isinstance(value, dict):
        if not value:
            lines.append(f"{pad}{prefix}{{}}")
            return
        first = True
        for key, item in value.items():
            head = f"{pad}{prefix}" if first and prefix else pad
            first = False
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{head}{_key(key)}:")
                _emit(item, (level + indent) if not prefix or not head.endswith(prefix) else level + indent, lines, indent)
            else:
                rendered = "{}" if isinstance(item, dict) else ("[]" if isinstance(item, list) else _scalar(item))
                lines.append(f"{head}{_key(key)}: {rendered}")
            if prefix and head.endswith(prefix):
                pad = " " * (level + len(prefix))
                level = level + len(prefix)
                prefix = ""
        return
    if isinstance(value, list):
        if not value:
            lines.append(f"{pad}{prefix}[]")
            return
        for item in value:
            if isinstance(item, dict) and item:
                _emit(item, level, lines, indent, prefix="- ")
            elif isinstance(item, list) and item:
                lines.append(f"{pad}-")
                _emit(item, level + indent, lines, indent)
            else:
                rendered = "{}" if isinstance(item, dict) else ("[]" if isinstance(item, list) else _scalar(item))
                lines.append(f"{pad}- {rendered}")
        return
    lines.append(f"{pad}{prefix}{_scalar(value)}")


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------
def _parse_scalar(text: str) -> Any:
    s = text.strip()
    if s == "" or s == "null" or s == "~":
        return None
    if s == "true":
        return True
    if s == "false":
        return False
    if s == "[]":
        return []
    if s == "{}":
        return {}
    if s.startswith('"'):
        try:
            return json.loads(s)
        except Exception:  # noqa: BLE001
            return s.strip('"')
    if s.startswith("'") and s.endswith("'") and len(s) >= 2:
        return s[1:-1].replace("''", "'")
    if _NUMBER.match(s):
        try:
            return int(s) if re.match(r"^-?\d+$", s) else float(s)
        except ValueError:
            return s
    return s


def _split_key(line: str) -> tuple[str, str] | None:
    """Split ``key: value`` honouring a quoted key."""
    if line.startswith('"'):
        try:
            end = 1
            while True:
                end = line.index('"', end)
                if line[end - 1] != "\\":
                    break
                end += 1
            key = json.loads(line[: end + 1])
            rest = line[end + 1:]
            if rest.startswith(":") and (len(rest) == 1 or rest[1] == " "):
                return key, rest[1:].strip()
            return None
        except Exception:  # noqa: BLE001
            return None
    match = re.match(r"^([^:#]+?):(?: (.*))?$", line)
    if not match:
        return None
    return match.group(1).strip(), (match.group(2) or "").strip()


def load(text: str) -> Any:
    raw_lines = [l.rstrip("\r\n") for l in str(text or "").split("\n")]
    lines = [(len(l) - len(l.lstrip(" ")), l.strip()) for l in raw_lines
             if l.strip() and not l.strip().startswith("#")]
    if not lines:
        return None
    value, _ = _parse_block(lines, 0, lines[0][0])
    return value


def _parse_block(lines: list, index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return None, index
    level, content = lines[index]
    if content.startswith("- ") or content == "-":
        return _parse_sequence(lines, index, indent)
    return _parse_mapping(lines, index, indent)


def _parse_mapping(lines: list, index: int, indent: int) -> tuple[dict, int]:
    result: dict = {}
    while index < len(lines):
        level, content = lines[index]
        if level < indent:
            break
        if level > indent:
            raise ValueError(f"unexpected indentation at line: {content}")
        if content.startswith("- "):
            break
        split = _split_key(content)
        if split is None:
            raise ValueError(f"not a mapping entry: {content}")
        key, rest = split
        if rest == "":
            if index + 1 < len(lines) and lines[index + 1][0] > indent:
                value, index = _parse_block(lines, index + 1, lines[index + 1][0])
            elif index + 1 < len(lines) and lines[index + 1][0] == indent and lines[index + 1][1].startswith("- "):
                value, index = _parse_sequence(lines, index + 1, indent)
            else:
                value, index = None, index + 1
        else:
            value, index = _parse_scalar(rest), index + 1
        result[key] = value
    return result, index


def _parse_sequence(lines: list, index: int, indent: int) -> tuple[list, int]:
    result: list = []
    while index < len(lines):
        level, content = lines[index]
        if level < indent or not (content.startswith("- ") or content == "-"):
            break
        if level > indent:
            raise ValueError(f"unexpected indentation at line: {content}")
        rest = content[2:].strip() if content != "-" else ""
        if rest == "":
            if index + 1 < len(lines) and lines[index + 1][0] > indent:
                value, index = _parse_block(lines, index + 1, lines[index + 1][0])
            else:
                value, index = None, index + 1
            result.append(value)
            continue
        split = _split_key(rest)
        if split is not None and not rest.startswith('"') or (split is not None and rest.startswith('"') and split[1] != "" or (split is not None and rest.startswith('"') and index + 1 < len(lines) and lines[index + 1][0] > indent)):
            # an inline mapping: re-indent its first line and parse the mapping at indent+2
            inner_indent = indent + 2
            lines[index] = (inner_indent, rest)
            value, index = _parse_mapping(lines, index, inner_indent)
            result.append(value)
            continue
        result.append(_parse_scalar(rest))
        index += 1
    return result, index
