# Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
Projects and Patchbooks on disk.

A project is a folder, and the folder is an iTailor project: iTailor's runs,
lessons, settings and knowledge graph live in its ``.itailor/``. Patchbook adds
a small metadata file and a ``patchbooks/`` folder of notebooks:

    <project>/
      patchbook-project.json       name, description, dates
      patchbooks/<id>.pbk.json     one Patchbook: a list of cells with their results
      data/                        a place for the user's files (any file anywhere in the folder is fine)
      ITAILOR.md                   what iTailor is told about the project at the start of every run
      .itailor/                    iTailor's own folder (runs, graph.yaml, lessons.jsonl, settings.json)

A Patchbook is a JSON document; a cell is a *patch* (plain language that
iTailor turns into code and runs), a *note* (Markdown) or a *code* cell (a
script written by hand). Results are stored in the cell so a Patchbook reopens
exactly as it was left.
"""

from __future__ import annotations

import csv
import json
import os
import random
import re
import shutil
import threading
import time
import uuid

from . import config

PROJECT_FILE = "patchbook-project.json"
PATCHBOOKS_DIR = "patchbooks"
PATCHBOOK_EXT = ".pbk.json"
SCHEMA = "patchbook/3"
HIDDEN_DIRS = {".itailor", "__pycache__", ".git", ".venv", "venv", "node_modules", PATCHBOOKS_DIR}
HIDDEN_FILES = {PROJECT_FILE, ".gitignore", ".DS_Store", "Thumbs.db"}
CELL_KINDS = ("patch", "note", "code")
ENGINES = ("quick", "thorough", "ask")
EFFORTS = ("low", "normal", "high", "max")
STATUSES = ("idle", "queued", "running", "done", "partial", "failed", "stopped", "stale")

_LOCK = threading.RLock()


class NotFound(Exception):
    pass


class Invalid(Exception):
    pass


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def uid(length: int = 8) -> str:
    return uuid.uuid4().hex[:length]


def slugify(text: str, fallback: str = "project", limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return (slug[:limit].strip("-") or fallback)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
def _meta_path(path: str) -> str:
    return os.path.join(path, PROJECT_FILE)


def _read_json_file(path: str, attempts: int = 6):
    """Read a JSON file; on Windows ``os.replace`` is not atomic for readers, so a
    file being replaced can be missing for an instant. Retry briefly, then give up.
    Returns the parsed value, or None when the file does not exist."""
    for attempt in range(attempts):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            # A replace in progress shows as a missing file for an instant; a .tmp sibling is the sign of one.
            if attempt < attempts - 1 and (attempt < 2 or os.path.exists(path + ".tmp")):
                time.sleep(0.03)
                continue
            return None
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.03)
    return None


def _replace_file(tmp: str, path: str, attempts: int = 8) -> None:
    for attempt in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05)


def _read_meta(path: str) -> dict | None:
    try:
        data = _read_json_file(_meta_path(path))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_meta(path: str, meta: dict) -> None:
    tmp = _meta_path(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2, ensure_ascii=False)
    _replace_file(tmp, _meta_path(path))


def _external_registry() -> dict:
    return {str(e.get("id")): str(e.get("path")) for e in (config.load().get("externalProjects") or [])
            if isinstance(e, dict) and e.get("id") and e.get("path")}


def project_path(project_id: str) -> str:
    """The folder of a project, or NotFound."""
    pid = str(project_id or "").strip()
    if not pid or "/" in pid or "\\" in pid or pid.startswith("."):
        raise NotFound(f"no such project: {project_id}")
    external = _external_registry().get(pid)
    if external and os.path.isfile(_meta_path(external)):
        return os.path.abspath(external)
    path = os.path.join(config.projects_dir(), pid)
    if os.path.isfile(_meta_path(path)):
        return os.path.abspath(path)
    raise NotFound(f"no such project: {project_id}")


def _summary(path: str, meta: dict, external: bool = False) -> dict:
    books = list_patchbooks_raw(path)
    return {
        "id": meta.get("id"), "name": meta.get("name") or os.path.basename(path), "description": meta.get("description", ""),
        "created": meta.get("created", ""), "updated": meta.get("updated", ""), "lastOpened": meta.get("lastOpened", ""),
        "path": path, "external": external, "patchbooks": len(books), "sample": bool(meta.get("sample")),
    }


def list_projects() -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    root = config.projects_dir()
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        meta = _read_meta(path) if os.path.isdir(path) else None
        if not meta:
            continue
        if meta.get("id") != name:
            meta["id"] = name
            _write_meta(path, meta)
        seen.add(name)
        out.append(_summary(path, meta))
    for pid, path in _external_registry().items():
        if pid in seen:
            continue
        meta = _read_meta(path)
        if meta:
            meta["id"] = pid
            out.append(_summary(path, meta, external=True))
    out.sort(key=lambda p: (p.get("lastOpened") or p.get("updated") or ""), reverse=True)
    return out


def get_project(project_id: str) -> dict:
    path = project_path(project_id)
    meta = _read_meta(path) or {}
    meta["id"] = project_id
    data = _summary(path, meta, external=project_id in _external_registry())
    data["patchbookList"] = list_patchbooks(project_id)
    data["itailorSettings"] = os.path.join(path, ".itailor", "settings.json")
    return data


ITAILOR_MD = """# ITAILOR.md

iTailor reads this file at the start of every run in this project. Keep it short
and factual: what the data is, what the project is for, conventions to follow.

## Project

- Name: {name}
- Purpose: {description}
- Data lives in: data/ (and anywhere else in this folder)
- Outputs: save tables, charts and reports in this folder with clear names

## Conventions

- Prefer CSV for tables and PNG for charts.
- Print a short plain-language summary of what was found.
"""


def _init_folder(path: str, meta: dict) -> None:
    os.makedirs(os.path.join(path, PATCHBOOKS_DIR), exist_ok=True)
    os.makedirs(os.path.join(path, "data"), exist_ok=True)
    os.makedirs(os.path.join(path, ".itailor"), exist_ok=True)
    _write_meta(path, meta)
    context = os.path.join(path, "ITAILOR.md")
    if not os.path.exists(context):
        with open(context, "w", encoding="utf-8") as handle:
            handle.write(ITAILOR_MD.format(name=meta.get("name", ""), description=meta.get("description") or "(not described yet)"))
    settings_path = os.path.join(path, ".itailor", "settings.json")
    if not os.path.exists(settings_path):
        from itailor import settings as settings_module
        settings_module.write_layer(settings_path, settings_module.SETTINGS_TEMPLATE)
    gitignore = os.path.join(path, ".gitignore")
    if not os.path.exists(gitignore):
        with open(gitignore, "w", encoding="utf-8") as handle:
            handle.write("__pycache__/\n.itailor/runs/\n.itailor/scratch/\n.itailor/env.json\n.itailor/settings.local.json\n")


def create_project(name: str, description: str = "", *, sample: bool = False) -> dict:
    name = str(name or "").strip() or "Untitled project"
    root = config.projects_dir()
    base = slugify(name)
    pid = base
    while os.path.exists(os.path.join(root, pid)):
        pid = f"{base}-{uid(4)}"
    path = os.path.join(root, pid)
    now = now_iso()
    meta = {"id": pid, "name": name, "description": str(description or ""), "created": now, "updated": now, "lastOpened": now,
            "sample": bool(sample)}
    with _LOCK:
        os.makedirs(path, exist_ok=False)
        _init_folder(path, meta)
        create_patchbook(pid, "Patchbook 1")
    return get_project(pid)


def import_folder(folder: str, name: str = "") -> dict:
    folder = os.path.abspath(os.path.expanduser(str(folder or "").strip()))
    if not os.path.isdir(folder):
        raise Invalid(f"not a folder: {folder}")
    root = config.projects_dir()
    if os.path.dirname(folder) == root:
        pid = os.path.basename(folder)
    else:
        existing = {v: k for k, v in _external_registry().items()}
        pid = existing.get(folder) or f"{slugify(name or os.path.basename(folder))}-{uid(4)}"
        entries = [e for e in config.load().get("externalProjects") or [] if str(e.get("id")) != pid]
        entries.append({"id": pid, "path": folder})
        config.save({"externalProjects": entries})
    meta = _read_meta(folder) or {}
    now = now_iso()
    meta.setdefault("created", now)
    meta.update({"id": pid, "name": str(name or meta.get("name") or os.path.basename(folder)), "updated": now, "lastOpened": now})
    meta.setdefault("description", "")
    with _LOCK:
        _init_folder(folder, meta)
        if not list_patchbooks_raw(folder):
            create_patchbook(pid, "Patchbook 1")
    return get_project(pid)


def update_project(project_id: str, patch: dict) -> dict:
    path = project_path(project_id)
    with _LOCK:
        meta = _read_meta(path) or {"id": project_id}
        if "name" in patch and str(patch["name"]).strip():
            meta["name"] = str(patch["name"]).strip()
        if "description" in patch:
            meta["description"] = str(patch["description"] or "")
        meta["updated"] = now_iso()
        _write_meta(path, meta)
    return get_project(project_id)


def touch_opened(project_id: str) -> dict:
    path = project_path(project_id)
    with _LOCK:
        meta = _read_meta(path) or {"id": project_id}
        meta["lastOpened"] = now_iso()
        _write_meta(path, meta)
    config.save({"lastProjectId": project_id})
    return get_project(project_id)


def delete_project(project_id: str) -> dict:
    path = project_path(project_id)
    external = project_id in _external_registry()
    with _LOCK:
        if external:
            entries = [e for e in config.load().get("externalProjects") or [] if str(e.get("id")) != project_id]
            config.save({"externalProjects": entries})
        else:
            shutil.rmtree(path)
        cfg = config.load()
        if cfg.get("lastProjectId") == project_id:
            config.save({"lastProjectId": ""})
    return {"ok": True, "removedFolder": not external, "path": path}


def duplicate_project(project_id: str, name: str = "") -> dict:
    src = project_path(project_id)
    meta = _read_meta(src) or {}
    name = str(name or "").strip() or f"{meta.get('name', project_id)} copy"
    root = config.projects_dir()
    base = slugify(name)
    pid = base
    while os.path.exists(os.path.join(root, pid)):
        pid = f"{base}-{uid(4)}"
    dst = os.path.join(root, pid)
    with _LOCK:
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", ".itailor"))
        now = now_iso()
        meta.update({"id": pid, "name": name, "created": now, "updated": now, "lastOpened": now, "sample": False})
        _init_folder(dst, meta)
    return get_project(pid)


# ---------------------------------------------------------------------------
# Patchbooks
# ---------------------------------------------------------------------------
def new_cell(kind: str = "patch", text: str = "", language: str = "auto", engine: str = "", effort: str = "") -> dict:
    now = now_iso()
    return {"id": uid(), "kind": kind if kind in CELL_KINDS else "patch", "text": str(text or ""),
            "language": str(language or "auto"), "engine": engine if engine in ENGINES else "",
            "effort": effort if effort in EFFORTS else "",
            "status": "idle", "executionCount": None, "result": None, "steps": [], "runId": "",
            "created": now, "updated": now, "finished": "",
            "options": {"showCode": None, "excluded": False, "pinned": False, "collapsed": False}}


def normalize_cell(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    cell = new_cell(raw.get("kind", "patch"), raw.get("text", ""), raw.get("language", "auto"), raw.get("engine", ""), raw.get("effort", ""))
    cell["id"] = str(raw.get("id") or cell["id"])
    status = str(raw.get("status") or "idle")
    cell["status"] = status if status in STATUSES else "idle"
    if cell["status"] in ("running", "queued"):
        cell["status"] = "stopped"
    count = raw.get("executionCount")
    cell["executionCount"] = int(count) if isinstance(count, (int, float)) else None
    cell["result"] = raw.get("result") if isinstance(raw.get("result"), dict) else None
    cell["steps"] = [s for s in (raw.get("steps") or []) if isinstance(s, dict)][-80:]
    cell["runId"] = str(raw.get("runId") or "")
    cell["created"] = str(raw.get("created") or cell["created"])
    cell["updated"] = str(raw.get("updated") or cell["updated"])
    cell["finished"] = str(raw.get("finished") or "")
    options = raw.get("options") if isinstance(raw.get("options"), dict) else {}
    cell["options"] = {"showCode": options.get("showCode") if isinstance(options.get("showCode"), bool) else None,
                       "excluded": bool(options.get("excluded")), "pinned": bool(options.get("pinned")),
                       "collapsed": bool(options.get("collapsed"))}
    return cell


def new_patchbook(name: str = "Untitled") -> dict:
    now = now_iso()
    return {"id": uid(), "schema": SCHEMA, "name": str(name or "Untitled"), "created": now, "updated": now,
            "executionCounter": 0, "settings": {"engine": "", "language": "auto", "effort": ""}, "cells": [new_cell()]}


def normalize_patchbook(raw, *, patchbook_id: str | None = None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    book = new_patchbook(raw.get("name") or "Untitled")
    book["id"] = str(patchbook_id or raw.get("id") or book["id"])
    book["created"] = str(raw.get("created") or book["created"])
    book["updated"] = str(raw.get("updated") or book["updated"])
    counter = raw.get("executionCounter")
    book["executionCounter"] = int(counter) if isinstance(counter, (int, float)) else 0
    settings = raw.get("settings") if isinstance(raw.get("settings"), dict) else {}
    book["settings"] = {"engine": settings.get("engine") if settings.get("engine") in ENGINES else "",
                        "language": str(settings.get("language") or "auto"),
                        "effort": settings.get("effort") if settings.get("effort") in EFFORTS else ""}
    cells = [normalize_cell(c) for c in (raw.get("cells") or []) if isinstance(c, dict)]
    book["cells"] = cells or [new_cell()]
    return book


def _books_dir(path: str) -> str:
    folder = os.path.join(path, PATCHBOOKS_DIR)
    os.makedirs(folder, exist_ok=True)
    return folder


def _book_path(path: str, patchbook_id: str) -> str:
    nid = str(patchbook_id or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", nid):
        raise NotFound(f"no such patchbook: {patchbook_id}")
    return os.path.join(_books_dir(path), nid + PATCHBOOK_EXT)


def list_patchbooks_raw(path: str) -> list[dict]:
    out = []
    folder = os.path.join(path, PATCHBOOKS_DIR)
    if not os.path.isdir(folder):
        return out
    for name in sorted(os.listdir(folder)):
        if not name.endswith(PATCHBOOK_EXT):
            continue
        nid = name[: -len(PATCHBOOK_EXT)]
        try:
            raw = _read_json_file(os.path.join(folder, name)) or {}
        except (OSError, ValueError):
            raw = {}
        book = normalize_patchbook(raw, patchbook_id=nid)
        cells = book["cells"]
        out.append({"id": nid, "name": book["name"], "created": book["created"], "updated": book["updated"],
                    "cells": len([c for c in cells if c["text"].strip() or c["result"]]),
                    "lastStatus": next((c["status"] for c in reversed(cells) if c["result"]), "")})
    out.sort(key=lambda b: b.get("created") or "")
    return out


def list_patchbooks(project_id: str) -> list[dict]:
    return list_patchbooks_raw(project_path(project_id))


def get_patchbook(project_id: str, patchbook_id: str) -> dict:
    file = _book_path(project_path(project_id), patchbook_id)
    try:
        raw = _read_json_file(file)
    except (OSError, ValueError) as exc:
        raise Invalid(f"could not read {file}: {exc}") from None
    if raw is None:
        raise NotFound(f"no such patchbook: {patchbook_id}")
    return normalize_patchbook(raw, patchbook_id=patchbook_id)


def save_patchbook(project_id: str, patchbook_id: str, data: dict) -> dict:
    path = project_path(project_id)
    file = _book_path(path, patchbook_id)
    book = normalize_patchbook(data, patchbook_id=patchbook_id)
    book["updated"] = now_iso()
    with _LOCK:
        tmp = file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(book, handle, indent=1, ensure_ascii=False)
        _replace_file(tmp, file)
        meta = _read_meta(path) or {"id": project_id}
        meta["updated"] = book["updated"]
        _write_meta(path, meta)
    return book


def create_patchbook(project_id: str, name: str = "") -> dict:
    existing = list_patchbooks(project_id)
    name = str(name or "").strip() or f"Patchbook {len(existing) + 1}"
    book = new_patchbook(name)
    while any(b["id"] == book["id"] for b in existing):
        book["id"] = uid()
    return save_patchbook(project_id, book["id"], book)


def update_cell(project_id: str, patchbook_id: str, cell_id: str, patch: dict, *, bump_counter: bool = False) -> dict:
    """Merge ``patch`` into one cell on disk (used when a run finishes). Returns the cell."""
    with _LOCK:
        book = get_patchbook(project_id, patchbook_id)
        cell = next((c for c in book["cells"] if c["id"] == cell_id), None)
        if cell is None:
            raise NotFound(f"no such cell: {cell_id}")
        if bump_counter:
            book["executionCounter"] = int(book.get("executionCounter") or 0) + 1
            cell["executionCount"] = book["executionCounter"]
        for key, value in patch.items():
            if key == "options" and isinstance(value, dict):
                cell["options"].update(value)
            else:
                cell[key] = value
        cell["updated"] = now_iso()
        save_patchbook(project_id, patchbook_id, book)
        return normalize_cell(cell)


def delete_patchbook(project_id: str, patchbook_id: str) -> dict:
    file = _book_path(project_path(project_id), patchbook_id)
    if not os.path.isfile(file):
        raise NotFound(f"no such patchbook: {patchbook_id}")
    with _LOCK:
        os.remove(file)
    return {"ok": True}


def duplicate_patchbook(project_id: str, patchbook_id: str, name: str = "") -> dict:
    book = get_patchbook(project_id, patchbook_id)
    copy = normalize_patchbook(json.loads(json.dumps(book)), patchbook_id=uid())
    copy["name"] = str(name or "").strip() or f"{book['name']} copy"
    copy["created"] = now_iso()
    for cell in copy["cells"]:
        cell["id"] = uid()
    return save_patchbook(project_id, copy["id"], copy)


# ---------------------------------------------------------------------------
# Files in the project folder
# ---------------------------------------------------------------------------
def safe_path(project_id: str, rel: str, *, must_exist: bool = True) -> tuple[str, str]:
    root = project_path(project_id)
    rel = str(rel or "").replace("\\", "/").strip("/")
    full = os.path.abspath(os.path.join(root, rel)) if rel else root
    if os.path.commonpath([root, full]) != root:
        raise Invalid("path is outside the project")
    if must_exist and not os.path.exists(full):
        raise NotFound(f"no such file: {rel}")
    return root, full


def list_files(project_id: str, limit: int = 4000) -> list[dict]:
    root = project_path(project_id)
    items: list[dict] = []
    for dirpath, dirs, files in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        dirs[:] = sorted(d for d in dirs if d not in HIDDEN_DIRS and not d.startswith("."))
        for d in dirs:
            items.append({"path": f"{rel_dir}/{d}" if rel_dir else d, "dir": True, "name": d})
        for f in sorted(files):
            if (not rel_dir and f in HIDDEN_FILES) or f.endswith(".tmp") or (rel_dir == "shared" and f == "state.json"):
                continue
            full = os.path.join(dirpath, f)
            try:
                stat = os.stat(full)
            except OSError:
                continue
            items.append({"path": f"{rel_dir}/{f}" if rel_dir else f, "dir": False, "name": f,
                          "size": stat.st_size, "mtime": stat.st_mtime})
        if len(items) >= limit:
            break
    return items[:limit]


def read_text(project_id: str, rel: str, limit: int = 300000) -> dict:
    _root, full = safe_path(project_id, rel)
    if os.path.isdir(full):
        raise Invalid("that is a folder")
    size = os.path.getsize(full)
    with open(full, "rb") as handle:
        data = handle.read(limit)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {"path": rel, "binary": True, "size": size}
    return {"path": rel, "text": text, "truncated": size > limit, "size": size}


def write_text(project_id: str, rel: str, text: str) -> dict:
    _root, full = safe_path(project_id, rel, must_exist=False)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="") as handle:
        handle.write(str(text or ""))
    return {"ok": True, "path": rel, "size": os.path.getsize(full)}


def save_upload(project_id: str, rel_dir: str, filename: str, stream) -> dict:
    name = os.path.basename(str(filename or "")).strip() or "upload"
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", name)
    _root, folder = safe_path(project_id, rel_dir, must_exist=False)
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, name)
    stem, ext = os.path.splitext(name)
    counter = 1
    while os.path.exists(target):
        counter += 1
        target = os.path.join(folder, f"{stem}-{counter}{ext}")
    with open(target, "wb") as handle:
        shutil.copyfileobj(stream, handle)
    rel = os.path.relpath(target, project_path(project_id)).replace(os.sep, "/")
    return {"ok": True, "path": rel, "size": os.path.getsize(target)}


def delete_path(project_id: str, rel: str) -> dict:
    root, full = safe_path(project_id, rel)
    if full == root:
        raise Invalid("cannot delete the project folder itself")
    base = os.path.basename(full)
    if base in HIDDEN_DIRS or base == PROJECT_FILE:
        raise Invalid("that item belongs to Patchbook")
    if os.path.isdir(full):
        shutil.rmtree(full)
    else:
        os.remove(full)
    return {"ok": True}


def make_dir(project_id: str, rel: str) -> dict:
    _root, full = safe_path(project_id, rel, must_exist=False)
    os.makedirs(full, exist_ok=True)
    return {"ok": True, "path": rel}


def _is_own(root: str, full: str) -> bool:
    """Patchbook's and iTailor's own files and folders are never moved, copied over or deleted from the Files panel."""
    rel = os.path.relpath(full, root).replace(os.sep, "/")
    first = rel.split("/")[0]
    return full == root or first in HIDDEN_DIRS or rel == PROJECT_FILE or first.startswith(".")


def _clean_name(name: str) -> str:
    name = os.path.basename(str(name or "").replace("\\", "/")).strip()
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", name)
    if not name or name in (".", ".."):
        raise Invalid("that is not a valid name")
    return name


def _unique(target: str) -> str:
    """``report.md`` -> ``report (2).md`` while the name is taken."""
    if not os.path.exists(target):
        return target
    folder, name = os.path.split(target)
    stem, ext = os.path.splitext(name)
    if os.path.isdir(target):
        stem, ext = name, ""
    counter = 2
    while True:
        candidate = os.path.join(folder, f"{stem} ({counter}){ext}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def _rel(root: str, full: str) -> str:
    return os.path.relpath(full, root).replace(os.sep, "/")


def rename_path(project_id: str, rel: str, new_name: str) -> dict:
    root, full = safe_path(project_id, rel)
    if _is_own(root, full):
        raise Invalid("that item belongs to Patchbook")
    target = os.path.join(os.path.dirname(full), _clean_name(new_name))
    if os.path.exists(target) and os.path.normcase(target) != os.path.normcase(full):
        raise Invalid("a file with that name already exists")
    os.rename(full, target)
    return {"ok": True, "path": _rel(root, target)}


def create_text_file(project_id: str, rel_dir: str, name: str, text: str = "") -> dict:
    root, folder = safe_path(project_id, rel_dir, must_exist=False)
    os.makedirs(folder, exist_ok=True)
    target = _unique(os.path.join(folder, _clean_name(name)))
    with open(target, "w", encoding="utf-8", newline="") as handle:
        handle.write(str(text or ""))
    return {"ok": True, "path": _rel(root, target)}


def _bulk(project_id: str, rels, action) -> dict:
    """Apply ``action(root, full)`` to every path; report each outcome instead of stopping at the first problem."""
    done, failed = [], []
    for rel in rels or []:
        try:
            root, full = safe_path(project_id, rel)
            if _is_own(root, full):
                raise Invalid("that item belongs to Patchbook")
            result = action(root, full)
            done.append({"path": rel, **(result or {})})
        except (Invalid, NotFound, OSError, shutil.Error) as exc:
            failed.append({"path": rel, "error": str(exc)})
    return {"ok": not failed, "done": done, "failed": failed}


def delete_paths(project_id: str, rels) -> dict:
    def action(root, full):
        if os.path.isdir(full):
            shutil.rmtree(full)
        else:
            os.remove(full)
    return _bulk(project_id, rels, action)


def duplicate_paths(project_id: str, rels) -> dict:
    def action(root, full):
        folder, name = os.path.split(full)
        stem, ext = (name, "") if os.path.isdir(full) else os.path.splitext(name)
        target = _unique(os.path.join(folder, f"{stem} copy{ext}"))
        if os.path.isdir(full):
            shutil.copytree(full, target)
        else:
            shutil.copy2(full, target)
        return {"created": _rel(root, target)}
    return _bulk(project_id, rels, action)


def copy_or_move_paths(project_id: str, rels, target_dir: str, *, move: bool) -> dict:
    root, folder = safe_path(project_id, target_dir, must_exist=False)
    if _is_own(root, folder) and folder != root:
        raise Invalid("that folder belongs to Patchbook")
    os.makedirs(folder, exist_ok=True)

    def action(_root, full):
        if os.path.isdir(full) and os.path.commonpath([full, folder]) == full:
            raise Invalid("a folder cannot be moved or copied into itself")
        target = os.path.join(folder, os.path.basename(full))
        if os.path.normcase(os.path.dirname(full)) == os.path.normcase(folder):
            if move:
                return {"created": _rel(root, full)}
            target = _unique(target)
        elif os.path.exists(target):
            target = _unique(target)
        if move:
            shutil.move(full, target)
        elif os.path.isdir(full):
            shutil.copytree(full, target)
        else:
            shutil.copy2(full, target)
        return {"created": _rel(root, target)}
    return _bulk(project_id, rels, action)


def zip_paths(project_id: str, rels):
    """A zip of the given files and folders, in memory, for downloading several at once."""
    import io
    import zipfile
    root = project_path(project_id)
    buffer = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for rel in rels or []:
            _r, full = safe_path(project_id, rel)
            if os.path.isdir(full):
                for dirpath, dirs, files in os.walk(full):
                    dirs[:] = [d for d in dirs if d not in HIDDEN_DIRS and not d.startswith(".")]
                    for name in files:
                        file_path = os.path.join(dirpath, name)
                        archive.write(file_path, _rel(root, file_path))
                        count += 1
            else:
                archive.write(full, _rel(root, full))
                count += 1
    buffer.seek(0)
    return buffer, count


# ---------------------------------------------------------------------------
# The sample project a first-time user can start with
# ---------------------------------------------------------------------------
SAMPLE_PATCHES = [
    ("note", "# Welcome to Patchbook\n\nEach block below is a *patch*: one instruction in plain language. "
             "Press **Run** on a patch and iTailor writes the code, runs it on this computer, reads the real output, "
             "fixes what breaks and shows you the result. The files it produces appear in the **Files** panel.\n\n"
             "The folder `data/` holds a small sample: `products.csv` and three months of `sales_*.csv`."),
    ("patch", "Describe data/products.csv: how many rows and columns it has, the column names, and the three most common categories. Write the same summary to summary.md."),
    ("patch", "Merge every data/sales_*.csv file into one table called merged_sales.csv, with a column named source that says which file each row came from. Print how many rows the merged table has."),
    ("patch", "Plot the distribution of price in data/products.csv as a histogram and save it as price_hist.png."),
]


def _write_sample_data(folder: str) -> None:
    rng = random.Random(7)
    categories = ["Books", "Toys", "Garden", "Kitchen", "Sports", "Office"]
    brands = ["Aster", "Birch", "Cobalt", "Dune", "Ember"]
    products = []
    with open(os.path.join(folder, "products.csv"), "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["product_id", "name", "category", "brand", "price", "stock"])
        for i in range(1, 121):
            category = rng.choice(categories)
            price = round(rng.uniform(3, 180) * (1.4 if category == "Sports" else 1.0), 2)
            products.append((i, price))
            writer.writerow([i, f"{category[:-1] if category.endswith('s') else category} {i}", category,
                             rng.choice(brands), price, rng.randint(0, 250)])
    for month in ("2026-01", "2026-02", "2026-03"):
        with open(os.path.join(folder, f"sales_{month}.csv"), "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["date", "product_id", "quantity", "unit_price", "country"])
            for _ in range(rng.randint(140, 220)):
                pid, price = rng.choice(products)
                day = rng.randint(1, 28)
                writer.writerow([f"{month}-{day:02d}", pid, rng.randint(1, 6), price, rng.choice(["DE", "FR", "NL", "AT", "CH"])])


def create_sample_project() -> dict:
    project = create_project("Sample project", "A small shop dataset to try Patchbook with: products and three months of sales.",
                             sample=True)
    pid = project["id"]
    path = project_path(pid)
    _write_sample_data(os.path.join(path, "data"))
    books = list_patchbooks(pid)
    book = get_patchbook(pid, books[0]["id"]) if books else new_patchbook("Getting started")
    book["name"] = "Getting started"
    book["cells"] = [new_cell(kind, text) for kind, text in SAMPLE_PATCHES]
    save_patchbook(pid, book["id"], book)
    return get_project(pid)
