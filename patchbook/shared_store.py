# Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
The shared store: what one patch leaves for the next, on disk, in any language.

Inside one script, values live in memory. At the boundary between patches
(and between languages) they go through the project's ``shared/`` folder:

    shared/<name>.csv|json|txt|...     a value (a table, a result, a text) for later patches
    shared/<name>.meta.json            optional: {"description": ..., "language": ...}
    shared/params.json                 small named parameters, one flat JSON object
    shared/methods/<name>.<ext>        a reusable function or script; its header says how to call it
                                       (a comment line "call: clean_names(df) -> df" and "description: ...")

Patchbook scans the folder deterministically after every run and keeps the
registry in ``shared/state.json``: name, kind, file, language, how to call,
description, and which Patchbook cell and run produced it. The registry is
mirrored into iTailor's project knowledge graph (``.itailor/graph.yaml``) as
``shared`` nodes linked to the runs, and a compact view goes into every prompt
so a later patch knows what exists, where, and how to use it.
"""

from __future__ import annotations

import json
import os
import re
import time

STORE_DIR = "shared"
STATE_FILE = "state.json"
PARAMS_FILE = "params.json"
METHODS_DIR = "methods"
META_SUFFIX = ".meta.json"
TABLE_EXT = {".csv", ".tsv", ".parquet", ".feather", ".xlsx"}
JSON_EXT = {".json", ".yaml", ".yml"}
TEXT_EXT = {".txt", ".md", ".html", ".tex", ".log"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"}
LANG_BY_EXT = {".py": "python", ".r": "r", ".R": "r", ".js": "javascript", ".mjs": "javascript", ".ts": "typescript", ".sh": "bash",
               ".ps1": "powershell", ".jl": "julia", ".sql": "sql", ".go": "go", ".rs": "rust", ".java": "java", ".rb": "ruby", ".lua": "lua"}

INSTRUCTIONS = (
    "SHARED STORE (how patches pass things to each other, also across languages): the folder shared/ holds what later "
    "patches may need. To hand something over, write it there in a language-neutral form: tables as CSV (shared/<name>.csv), "
    "small results as JSON, text as .md/.txt, small named parameters as keys in shared/params.json (one flat JSON object; read it, "
    "update it, write it back), and reusable functions as source files under shared/methods/<name>.<ext> whose first lines contain a "
    "comment 'call: <how to call it>' and 'description: <what it does>'. Patchbook registers everything in shared/ after the run and "
    "tells later patches what exists. Read what is listed below instead of recomputing it."
)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def store_dir(project: str) -> str:
    return os.path.join(project, STORE_DIR)


def state_path(project: str) -> str:
    return os.path.join(store_dir(project), STATE_FILE)


def empty() -> dict:
    return {"version": 1, "updated": "", "variables": {}, "parameters": {}, "methods": {}}


def load(project: str) -> dict:
    try:
        with open(state_path(project), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            base = empty()
            base.update({k: v for k, v in data.items() if k in base})
            return base
    except (OSError, ValueError):
        pass
    return empty()


def _kind(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    if ext in TABLE_EXT:
        return "table"
    if ext in JSON_EXT:
        return "json"
    if ext in TEXT_EXT:
        return "text"
    if ext in IMAGE_EXT:
        return "image"
    return "binary"


def _meta(path: str) -> dict:
    try:
        with open(path + META_SUFFIX, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _header_fields(path: str) -> dict:
    """``call:`` and ``description:`` lines in the first 25 lines of a method file."""
    out: dict = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for _ in range(25):
                line = handle.readline()
                if not line:
                    break
                m = re.search(r"\bcall\s*:\s*(.+)", line, re.IGNORECASE)
                if m and "call" not in out:
                    out["call"] = m.group(1).strip().rstrip("*/").strip()
                m = re.search(r"\bdescription\s*:\s*(.+)", line, re.IGNORECASE)
                if m and "description" not in out:
                    out["description"] = m.group(1).strip().rstrip("*/").strip()
    except OSError:
        pass
    return out


def _rel(project: str, path: str) -> str:
    return os.path.relpath(path, project).replace(os.sep, "/")


def sync(project: str, producer: dict | None = None) -> dict:
    """Scan ``shared/`` and bring the registry up to date. ``producer`` (patchbook, cell, run)
    is recorded on entries that are new or changed since the last scan. Returns the registry."""
    root = store_dir(project)
    registry = load(project)
    previous = json.loads(json.dumps(registry))
    if not os.path.isdir(root):
        return registry
    seen_vars: set[str] = set()
    seen_methods: set[str] = set()
    stamp = _now()
    for dirpath, dirs, files in os.walk(root):
        rel_dir = _rel(project, dirpath)
        is_methods = rel_dir.startswith(f"{STORE_DIR}/{METHODS_DIR}")
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
        for name in sorted(files):
            if name.startswith(".") or name.endswith(META_SUFFIX) or name.endswith(".tmp"):
                continue
            full = os.path.join(dirpath, name)
            if dirpath == root and name in (STATE_FILE, PARAMS_FILE):
                continue
            try:
                stat = os.stat(full)
            except OSError:
                continue
            rel = _rel(project, full)
            meta = _meta(full)
            if is_methods:
                key = os.path.splitext(name)[0]
                entry = registry["methods"].get(key) or {}
                changed = entry.get("file") != rel or entry.get("size") != stat.st_size or abs(float(entry.get("mtime") or 0) - stat.st_mtime) > 0.5
                header = _header_fields(full)
                entry.update({"file": rel, "language": meta.get("language") or LANG_BY_EXT.get(os.path.splitext(name)[1], os.path.splitext(name)[1].lstrip(".")),
                              "call": meta.get("call") or header.get("call") or entry.get("call") or "",
                              "description": meta.get("description") or header.get("description") or entry.get("description") or "",
                              "size": stat.st_size, "mtime": stat.st_mtime})
                if changed:
                    entry["updated"] = stamp
                    if producer:
                        entry["producedBy"] = dict(producer)
                entry.setdefault("updated", stamp)
                registry["methods"][key] = entry
                seen_methods.add(key)
            else:
                key = os.path.splitext(name)[0] if dirpath == root else rel[len(STORE_DIR) + 1:]
                entry = registry["variables"].get(key) or {}
                changed = entry.get("file") != rel or entry.get("size") != stat.st_size or abs(float(entry.get("mtime") or 0) - stat.st_mtime) > 0.5
                entry.update({"file": rel, "kind": _kind(name), "language": meta.get("language") or entry.get("language") or "",
                              "description": meta.get("description") or entry.get("description") or "", "size": stat.st_size, "mtime": stat.st_mtime})
                if entry["kind"] == "table" and name.lower().endswith((".csv", ".tsv")):
                    entry["columns"], entry["rows"] = _csv_shape(full, "\t" if name.lower().endswith(".tsv") else ",")
                if changed:
                    entry["updated"] = stamp
                    if producer:
                        entry["producedBy"] = dict(producer)
                entry.setdefault("updated", stamp)
                registry["variables"][key] = entry
                seen_vars.add(key)
    for key in list(registry["variables"]):
        if key not in seen_vars:
            del registry["variables"][key]
    for key in list(registry["methods"]):
        if key not in seen_methods:
            del registry["methods"][key]
    # parameters: a flat JSON object
    params: dict = {}
    params_file = os.path.join(root, PARAMS_FILE)
    if os.path.isfile(params_file):
        try:
            with open(params_file, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            params = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            params = {}
    new_params: dict = {}
    for key, value in params.items():
        old = registry["parameters"].get(key) or {}
        entry = {"value": value, "updated": old.get("updated") or stamp}
        if old.get("value") != value or not old:
            entry["updated"] = stamp
            if producer:
                entry["producedBy"] = dict(producer)
        elif old.get("producedBy"):
            entry["producedBy"] = old["producedBy"]
        new_params[key] = entry
    registry["parameters"] = new_params
    if json.dumps(registry, sort_keys=True, default=str) != json.dumps(previous, sort_keys=True, default=str):
        registry["updated"] = stamp
        _write(project, registry)
        _mirror(project, registry)
    return registry


def _csv_shape(path: str, sep: str) -> tuple[list, int]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as handle:
            header = handle.readline().rstrip("\r\n")
            rows = sum(1 for line in handle if line.strip())
        return [c.strip().strip('"') for c in header.split(sep)][:40], rows
    except OSError:
        return [], 0


def _write(project: str, registry: dict) -> None:
    os.makedirs(store_dir(project), exist_ok=True)
    tmp = state_path(project) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(registry, handle, indent=1, ensure_ascii=False, default=str)
    os.replace(tmp, state_path(project))


def _mirror(project: str, registry: dict) -> None:
    """The registry as nodes of iTailor's project knowledge graph (derived; re-mirrored on every change)."""
    try:
        from itailor.graph import ProjectGraph, graph_path
        graph = ProjectGraph(graph_path(project))
        for node_id in list(graph.nodes):
            if graph.nodes[node_id].get("kind") == "shared":
                del graph.nodes[node_id]
        graph.data["edges"] = [e for e in graph.edges if not (e["src"].startswith("shared:") or e["dst"].startswith("shared:"))]

        def add(node_id: str, **attrs) -> None:
            graph.node(node_id, "shared", **attrs)
            producer = attrs.get("producedBy") or {}
            run_id = producer.get("run") if isinstance(producer, dict) else None
            if run_id and f"run:{run_id}" in graph.nodes:
                graph.edge(f"run:{run_id}", "produced", node_id)

        for name, entry in registry.get("variables", {}).items():
            add(f"shared:variable:{name}", type="variable", label=name, file=entry.get("file"), valueKind=entry.get("kind"),
                language=entry.get("language") or None, description=entry.get("description") or None, columns=entry.get("columns"),
                rows=entry.get("rows"), updated=entry.get("updated"), producedBy=entry.get("producedBy"))
        for name, entry in registry.get("parameters", {}).items():
            add(f"shared:parameter:{name}", type="parameter", label=name, value=entry.get("value"), updated=entry.get("updated"),
                producedBy=entry.get("producedBy"))
        for name, entry in registry.get("methods", {}).items():
            add(f"shared:method:{name}", type="method", label=name, file=entry.get("file"), language=entry.get("language"),
                call=entry.get("call") or None, description=entry.get("description") or None, updated=entry.get("updated"),
                producedBy=entry.get("producedBy"))
        graph.save()
    except Exception:  # noqa: BLE001 - the graph is derived data; never fail a run over it
        pass


def prompt_block(project: str, max_chars: int = 1800) -> str:
    """What the model is told about the store: the instructions and what is in it now."""
    registry = load(project)
    lines = []
    for name, entry in sorted(registry.get("variables", {}).items()):
        extra = ""
        if entry.get("kind") == "table" and entry.get("columns"):
            extra = f", {entry.get('rows', '?')} rows, columns: {', '.join(entry['columns'][:12])}"
        lines.append(f"- value '{name}': {entry.get('kind')} at {entry.get('file')}{extra}" + (f" ({entry['description']})" if entry.get("description") else "")
                     + _by(entry))
    for name, entry in sorted(registry.get("parameters", {}).items()):
        value = json.dumps(entry.get("value"), default=str)
        lines.append(f"- parameter {name} = {value[:120]} (in {STORE_DIR}/{PARAMS_FILE})" + _by(entry))
    for name, entry in sorted(registry.get("methods", {}).items()):
        lines.append(f"- method '{name}' ({entry.get('language')}) at {entry.get('file')}" + (f": call {entry['call']}" if entry.get("call") else "")
                     + (f" ({entry['description']})" if entry.get("description") else "") + _by(entry))
    body = "\n".join(lines) if lines else "(empty so far)"
    if len(body) > max_chars:
        body = body[:max_chars] + "\n... (more in shared/state.json)"
    return INSTRUCTIONS + "\nIN THE STORE NOW:\n" + body


def _by(entry: dict) -> str:
    producer = entry.get("producedBy") or {}
    if isinstance(producer, dict) and producer.get("cell"):
        return f" [from patch {producer['cell']}]"
    return ""
