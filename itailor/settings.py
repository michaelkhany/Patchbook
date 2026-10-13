# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
Layered settings, the way Claude Code and Patch Code define them:

  1. built-in defaults
  2. user          ~/.itailor/config.json
  3. project       <project>/.itailor/settings.json        (committed)
  4. local         <project>/.itailor/settings.local.json  (git-ignored)
  5. environment   ITAILOR_* variables
  6. explicit overrides from the caller

Later layers win for scalars; ``permissions.allow/deny/ask``, ``env``,
``hooks``, ``sandbox``, ``budgets``, ``privacy`` and ``autoModelExclude`` are
merged so a project can add rules without dropping the user's. The context
file (``ITAILOR.md``) is loaded from the project and its parents, plus the
user directory.
"""

from __future__ import annotations

import json
import os
import re

DIRNAME = ".itailor"
CONTEXT_FILENAME = "ITAILOR.md"
AUTO_MODEL = "auto"
PERMISSION_MODES = ("default", "acceptEdits", "plan", "bypassPermissions")

DEFAULTS: dict = {
    "provider": "gwdg",
    "baseUrl": "",
    "model": AUTO_MODEL,
    "apiKeyEnv": "",
    "permissionMode": "default",
    "permissions": {"allow": [], "deny": [], "ask": []},
    "profile": "desktop",
    "maxSteps": 40,                 # tool steps in one turn
    "maxIterations": 6,             # repair attempts in the script engine
    "commandTimeoutSeconds": 120,
    "runTimeoutSeconds": 180,
    "modelTimeoutSeconds": 180,
    "permissionTimeoutSeconds": 300,
    "consultTimeoutSeconds": 600,
    "maxTokens": 4000,
    "temperature": 0.1,
    "contextTokens": 60000,
    "toolCalling": "auto",          # auto | native | text
    "streaming": True,
    "contextFiles": [CONTEXT_FILENAME],
    "autoModelExclude": [],
    "env": {},
    "hooks": {},
    "sandbox": {"confineToProject": True, "allowNetwork": True, "mode": ""},
    "webSearch": True,
    "language": "auto",
    "privacy": {"localOnly": False, "maxPriceOut": None},
    "budgets": {"steps": 20, "repairsPerStep": 3, "replans": 2, "minutes": 30, "toolStepsPerStep": 25},
    "modelBandit": False,
    "approvePlans": False,
    "lessonsScope": "project",
    "orgPolicyPath": "",
    "discoverApps": True,
    "envCacheHours": 24,
    "maxContextFileBytes": 60000,
}

_MERGED_LISTS = ("allow", "deny", "ask")


def user_dir() -> str:
    return os.path.join(os.environ.get("ITAILOR_HOME") or os.path.expanduser("~"), DIRNAME)


def user_config_path() -> str:
    return os.path.join(user_dir(), "config.json")


def project_dir(project: str) -> str:
    return os.path.join(project, DIRNAME)


def project_settings_path(project: str) -> str:
    return os.path.join(project_dir(project), "settings.json")


def local_settings_path(project: str) -> str:
    return os.path.join(project_dir(project), "settings.local.json")


def _strip_comments(text: str) -> str:
    """Remove // and /* */ comments outside string literals (a URL inside a string survives)."""
    out: list[str] = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def read_json(path: str):
    """``None`` when absent, ``{"__error": ...}`` when unreadable. Comments and
    trailing commas are tolerated (settings.json style)."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        return None
    except OSError as exc:
        return {"__error": f"{path}: {exc}"}
    stripped = _strip_comments(text)
    stripped = re.sub(r",(\s*[}\]])", r"\1", stripped)
    try:
        data = json.loads(stripped or "{}")
    except Exception as exc:  # noqa: BLE001
        return {"__error": f"{path}: {exc}"}
    return data if isinstance(data, dict) else {}


def _uniq(items) -> list:
    out, seen = [], set()
    for item in items or []:
        if isinstance(item, str) and item.strip() and item.strip() not in seen:
            seen.add(item.strip())
            out.append(item.strip())
    return out


def merge_layer(base: dict, layer: dict | None) -> dict:
    if not isinstance(layer, dict):
        return base
    out = dict(base)
    for key, value in layer.items():
        if value is None or key == "__error":
            continue
        if key == "permissions" and isinstance(value, dict):
            out["permissions"] = {k: _uniq([*(base.get("permissions", {}).get(k) or []), *(value.get(k) or [])])
                                  for k in _MERGED_LISTS}
        elif key in ("env", "sandbox", "privacy", "budgets") and isinstance(value, dict):
            out[key] = {**(base.get(key) or {}), **value}
        elif key == "hooks" and isinstance(value, dict):
            merged = {k: list(v) for k, v in (base.get("hooks") or {}).items()}
            for event, entries in value.items():
                if isinstance(entries, list):
                    merged[event] = [*(merged.get(event) or []), *entries]
            out["hooks"] = merged
        elif key == "autoModelExclude" and isinstance(value, list):
            out[key] = _uniq([*(base.get(key) or []), *value])
        else:
            out[key] = value
    return out


def _clamp(value, lo, hi, fallback):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return int(max(lo, min(hi, round(number))))


def environment_layer() -> dict:
    layer: dict = {}
    mapping = {"ITAILOR_PERMISSION_MODE": "permissionMode", "ITAILOR_MODEL": "model",
               "ITAILOR_BASE_URL": "baseUrl", "ITAILOR_PROFILE": "profile",
               "ITAILOR_ORG_POLICY": "orgPolicyPath", "ITAILOR_TOOL_CALLING": "toolCalling"}
    for var, key in mapping.items():
        value = os.environ.get(var)
        if value:
            layer[key] = value.strip()
    if os.environ.get("ITAILOR_SANDBOX"):
        layer["sandbox"] = {"mode": os.environ["ITAILOR_SANDBOX"].strip().lower()}
    if os.environ.get("ITAILOR_LOCAL_ONLY", "").lower() in ("1", "true", "yes"):
        layer["privacy"] = {"localOnly": True}
    return layer


def load(project: str | None = None, overrides: dict | None = None) -> dict:
    """Every layer merged. The result also carries ``_sources`` and ``_errors``."""
    settings = json.loads(json.dumps(DEFAULTS))
    sources, errors = [], []
    layers = [("user", user_config_path())]
    if project:
        layers += [("project", project_settings_path(project)), ("local", local_settings_path(project))]
    for name, path in layers:
        data = read_json(path)
        if data is None:
            continue
        if "__error" in data:
            errors.append(data["__error"])
            continue
        sources.append({"name": name, "file": path})
        settings = merge_layer(settings, data)
    env_layer = environment_layer()
    if env_layer:
        sources.append({"name": "environment", "file": "ITAILOR_*"})
        settings = merge_layer(settings, env_layer)
    if overrides:
        sources.append({"name": "overrides", "file": "(caller)"})
        settings = merge_layer(settings, overrides)
    if settings.get("permissionMode") not in PERMISSION_MODES:
        settings["permissionMode"] = "default"
    settings["maxSteps"] = _clamp(settings.get("maxSteps"), 1, 400, DEFAULTS["maxSteps"])
    settings["maxIterations"] = _clamp(settings.get("maxIterations"), 0, 50, DEFAULTS["maxIterations"])
    for key in ("commandTimeoutSeconds", "runTimeoutSeconds", "modelTimeoutSeconds"):
        settings[key] = _clamp(settings.get(key), 5, 3600, DEFAULTS[key])
    settings["maxTokens"] = _clamp(settings.get("maxTokens"), 256, 200000, DEFAULTS["maxTokens"])
    settings["_sources"] = sources
    settings["_errors"] = errors
    settings["_project"] = os.path.abspath(project) if project else ""
    return settings


def load_context_files(project: str | None, names: list | None = None, max_bytes: int = 60000) -> list[dict]:
    """Walk from the project upward and collect ITAILOR.md files (outermost first),
    plus ~/.itailor/ITAILOR.md and <project>/.itailor/ITAILOR.md."""
    wanted = names or [CONTEXT_FILENAME]
    found: list[dict] = []
    seen: set[str] = set()

    def try_dir(directory: str, scope: str) -> None:
        for name in wanted:
            file = os.path.join(directory, name)
            if file in seen:
                continue
            seen.add(file)
            try:
                if not os.path.isfile(file):
                    continue
                with open(file, "r", encoding="utf-8", errors="replace") as handle:
                    text = handle.read()
                if len(text) > max_bytes:
                    text = text[:max_bytes] + "\n\n[truncated]"
                found.append({"file": file, "scope": scope, "text": text})
            except OSError:
                continue

    try_dir(user_dir(), "user")
    if project:
        chain = []
        directory = os.path.abspath(project)
        while True:
            chain.append(directory)
            parent = os.path.dirname(directory)
            if parent == directory:
                break
            directory = parent
        for d in reversed(chain):
            try_dir(d, "project" if d == os.path.abspath(project) else "parent")
        try_dir(project_dir(project), "project")
    return found


def write_layer(path: str, patch: dict) -> dict:
    existing = read_json(path)
    base = existing if isinstance(existing, dict) and "__error" not in existing else {}
    merged = {**base, **patch}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2)
        handle.write("\n")
    return merged


def add_permission_rule(path: str, list_name: str, rule: str) -> dict:
    existing = read_json(path)
    base = existing if isinstance(existing, dict) and "__error" not in existing else {}
    permissions = {"allow": [], "deny": [], "ask": [], **(base.get("permissions") or {})}
    if rule not in permissions.setdefault(list_name, []):
        permissions[list_name].append(rule)
    return write_layer(path, {"permissions": permissions})


CONTEXT_TEMPLATE = """# ITAILOR.md

This file is read by iTailor at the start of every run, the same way Claude
Code reads CLAUDE.md. Keep it short and factual: what the project is, how to
build and test it, conventions the agent must follow.

## Project

- Purpose:
- Main language(s):
- Entry point(s):
- Data lives in:

## Build & test

- Install:
- Build:
- Test:
- Lint:

## Conventions

- Style:
- Do not touch:
- Outputs go to:
"""

SETTINGS_TEMPLATE = {
    "permissionMode": "default",
    "permissions": {
        "allow": ["Shell(git status*)", "Shell(git diff*)", "Shell(git log*)"],
        "deny": ["Write(.env*)", "Edit(.env*)", "Shell(git push*)"],
        "ask": [],
    },
    "sandbox": {"confineToProject": True, "allowNetwork": True},
    "budgets": {"steps": 20, "repairsPerStep": 3, "replans": 2, "minutes": 30},
}
