# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
File tools: Read, Write, Edit, ListDir, Glob, Grep.

Every path is resolved against the project root and, when the sandbox
confines the agent to the project, a path that escapes it is refused before
anything is touched (``itailor.sandbox.resolve_path``).
"""

from __future__ import annotations

import os
import re
import time

from ..policy.rules import glob_to_regex
from ..sandbox import rel_of, resolve_path

IGNORED_DIRS = {"node_modules", ".git", ".hg", ".svn", "dist", "build", "out", "__pycache__", ".venv", "venv",
                ".tox", ".mypy_cache", ".pytest_cache", ".idea", "target", ".next", ".nuxt", "coverage",
                ".itailor", ".patchcode", ".cache", ".gradle", "bin", "obj"}
MAX_READ_BYTES = 2 * 1024 * 1024
MAX_GREP_FILE_BYTES = 1024 * 1024


def looks_binary(data: bytes) -> bool:
    sample = data[:4096]
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    suspicious = sum(1 for b in sample if b < 7 or 14 < b < 32)
    return suspicious / len(sample) > 0.1


def read_file(root: str, args: dict, *, confine: bool = True) -> dict:
    try:
        absolute = resolve_path(root, args.get("path"), confine=confine, must_exist=True)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    if os.path.isdir(absolute):
        return {"error": f"'{args.get('path')}' is a directory. Use ListDir."}
    size = os.path.getsize(absolute)
    if size > MAX_READ_BYTES:
        return {"error": f"File is {size} bytes; the limit is {MAX_READ_BYTES}. Read a slice with offset/limit or Grep it."}
    with open(absolute, "rb") as handle:
        data = handle.read()
    if looks_binary(data):
        return {"path": rel_of(root, absolute), "binary": True, "bytes": size, "note": "Binary file; contents not shown."}
    text = data.decode("utf-8", "replace")
    lines = text.split("\n")
    offset = max(1, int(args.get("offset") or 1))
    limit = max(1, min(int(args.get("limit") or 2000), 5000))
    chunk = lines[offset - 1: offset - 1 + limit]
    width = len(str(offset + len(chunk)))
    body = "\n".join(f"{str(offset + i).rjust(width)}\t{line.rstrip(chr(13))}" for i, line in enumerate(chunk))
    return {"path": rel_of(root, absolute), "totalLines": len(lines), "offset": offset, "shown": len(chunk),
            "truncated": offset - 1 + len(chunk) < len(lines), "content": body}


def write_file(root: str, args: dict, *, confine: bool = True) -> dict:
    try:
        absolute = resolve_path(root, args.get("path"), confine=confine)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    content = "" if args.get("content") is None else str(args.get("content"))
    existed = os.path.exists(absolute)
    os.makedirs(os.path.dirname(absolute) or ".", exist_ok=True)
    with open(absolute, "w", encoding="utf-8", newline="") as handle:
        handle.write(content)
    return {"path": rel_of(root, absolute), "action": "updated" if existed else "created",
            "bytes": len(content.encode("utf-8")), "lines": len(content.split("\n"))}


def edit_file(root: str, args: dict, *, confine: bool = True) -> dict:
    try:
        absolute = resolve_path(root, args.get("path"), confine=confine, must_exist=True)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    old = "" if args.get("old_string") is None else str(args.get("old_string"))
    new = "" if args.get("new_string") is None else str(args.get("new_string"))
    if not old:
        return {"error": "old_string must not be empty. Use Write to create a file."}
    if old == new:
        return {"error": "old_string and new_string are identical."}
    with open(absolute, "r", encoding="utf-8", errors="replace", newline="") as handle:
        text = handle.read()
    needle = old
    count = text.count(needle)
    if count == 0 and "\r\n" in text and "\r\n" not in needle:
        needle = old.replace("\n", "\r\n")
        count = text.count(needle)
    if count == 0:
        normalise = lambda s: "\n".join(l.rstrip() for l in s.replace("\r\n", "\n").split("\n"))  # noqa: E731
        n_text, n_old = normalise(text), normalise(old)
        if n_text.count(n_old) == 1:
            start = n_text.index(n_old)
            before = n_text[:start].count("\n")
            old_lines = n_old.count("\n") + 1
            eol = "\r\n" if "\r\n" in text else "\n"
            lines = text.replace("\r\n", "\n").split("\n")
            lines[before: before + old_lines] = new.replace("\r\n", "\n").split("\n")
            updated = eol.join(lines)
            with open(absolute, "w", encoding="utf-8", newline="") as handle:
                handle.write(updated)
            return {"path": rel_of(root, absolute), "replaced": 1, "note": "Matched ignoring trailing whitespace."}
        return {"error": f"old_string was not found in {args.get('path')}. Read the file again and copy the exact text (whitespace matters)."}
    if count > 1 and not args.get("replace_all"):
        return {"error": f"old_string occurs {count} times in {args.get('path')}. Include more surrounding context to make it unique, or pass replace_all: true."}
    replacement = new.replace("\n", "\r\n") if ("\r\n" in needle and "\n" in new and "\r\n" not in new) else new
    updated = text.replace(needle, replacement) if args.get("replace_all") else text.replace(needle, replacement, 1)
    with open(absolute, "w", encoding="utf-8", newline="") as handle:
        handle.write(updated)
    return {"path": rel_of(root, absolute), "replaced": count if args.get("replace_all") else 1, "preview": new[:400]}


def walk(root: str, *, max_entries: int = 5000, max_depth: int = 12, include_ignored: bool = False):
    count = 0
    stack = [(root, 0)]
    while stack:
        directory, depth = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            if not include_ignored and (entry.name in IGNORED_DIRS or (
                    entry.name.startswith(".") and entry.is_dir() and entry.name != ".github")):
                continue
            yield entry, depth
            count += 1
            if count >= max_entries:
                return
            if entry.is_dir(follow_symlinks=False) and depth + 1 < max_depth:
                stack.append((entry.path, depth + 1))


def list_dir(root: str, args: dict, *, confine: bool = True) -> dict:
    try:
        absolute = resolve_path(root, args.get("path") or ".", confine=confine, must_exist=True)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    depth = max(1, min(int(args.get("depth") or 2), 6))
    lines, total = [], 0
    for entry, level in walk(absolute, max_depth=depth, max_entries=800):
        total += 1
        size = ""
        if entry.is_file():
            try:
                size = f"  {entry.stat().st_size} B"
            except OSError:
                pass
        lines.append(f"{'  ' * level}{entry.name}{'/' if entry.is_dir() else size}")
    return {"path": rel_of(root, absolute), "entries": total, "listing": "\n".join(lines) or "(empty)"}


def glob(root: str, args: dict, *, confine: bool = True) -> dict:
    try:
        base = resolve_path(root, args.get("path") or ".", confine=confine, must_exist=True)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    pattern = str(args.get("pattern") or "").strip().replace("\\", "/")
    if not pattern:
        return {"error": 'pattern is required, e.g. "**/*.py".'}
    regex = glob_to_regex(pattern)
    matches = []
    for entry, _level in walk(base, max_entries=20000, max_depth=20):
        if not entry.is_file():
            continue
        rel = os.path.relpath(entry.path, base).replace(os.sep, "/")
        if regex.match(rel) or regex.match(entry.name):
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                mtime = 0
            matches.append((rel_of(root, entry.path), mtime))
            if len(matches) >= 500:
                break
    matches.sort(key=lambda m: -m[1])
    return {"pattern": pattern, "count": len(matches), "files": [m[0] for m in matches], "truncated": len(matches) >= 500}


def grep(root: str, args: dict, *, confine: bool = True) -> dict:
    try:
        base = resolve_path(root, args.get("path") or ".", confine=confine, must_exist=True)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    pattern = str(args.get("pattern") or "")
    if not pattern:
        return {"error": "pattern is required."}
    try:
        regex = re.compile(pattern, re.IGNORECASE if args.get("case_insensitive") else 0)
    except re.error as exc:
        return {"error": f"Invalid regular expression: {exc}"}
    file_filter = glob_to_regex(str(args.get("glob"))) if args.get("glob") else None
    max_results = max(1, min(int(args.get("max_results") or 100), 500))
    context = max(0, min(int(args.get("context") or 0), 5))
    files = [base] if os.path.isfile(base) else [
        e.path for e, _ in walk(base, max_entries=20000, max_depth=20)
        if e.is_file() and (not file_filter or file_filter.match(e.name)
                            or file_filter.match(os.path.relpath(e.path, base).replace(os.sep, "/")))]
    results, scanned = [], 0
    for file in files:
        if len(results) >= max_results:
            break
        try:
            if os.path.getsize(file) > MAX_GREP_FILE_BYTES:
                continue
            with open(file, "rb") as handle:
                data = handle.read()
        except OSError:
            continue
        if looks_binary(data):
            continue
        scanned += 1
        lines = data.decode("utf-8", "replace").split("\n")
        rel = rel_of(root, file)
        for i, line in enumerate(lines):
            if not regex.search(line):
                continue
            if context:
                lo, hi = max(0, i - context), min(len(lines) - 1, i + context)
                block = [f"{rel}{':' if j == i else '-'}{j + 1}{':' if j == i else '-'} {lines[j].rstrip()}" for j in range(lo, hi + 1)]
                results.append("\n".join(block))
            else:
                results.append(f"{rel}:{i + 1}: {line.rstrip()[:400]}")
            if len(results) >= max_results:
                break
    return {"pattern": pattern, "filesScanned": scanned, "matches": len(results),
            "truncated": len(results) >= max_results, "results": "\n".join(results) or "(no matches)"}


def snapshot(directory: str) -> set:
    try:
        return set(os.listdir(directory))
    except OSError:
        return set()


def new_files(directory: str, before: set, skip: set | None = None) -> list[str]:
    skip = skip or set()
    out = []
    for name in sorted(snapshot(directory)):
        if name in before or name in skip:
            continue
        full = os.path.join(directory, name)
        if os.path.isfile(full):
            out.append(full)
    return out


def recently_modified(directory: str, since: float, *, skip: set | None = None, limit: int = 200) -> list[str]:
    """Files under ``directory`` (top level and one below) modified after ``since``."""
    skip = skip or set()
    out = []
    for entry, _ in walk(directory, max_entries=5000, max_depth=2):
        if not entry.is_file() or entry.name in skip:
            continue
        try:
            if entry.stat().st_mtime >= since - 1:
                out.append(entry.path)
        except OSError:
            continue
        if len(out) >= limit:
            break
    return out


def touch_marker() -> float:
    return time.time()
