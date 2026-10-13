# Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
Where Patchbook keeps what it stores, and the application's own settings.

Everything a user produces lives under one data folder (``./data`` next to
``app.py``, or ``PATCHBOOK_HOME``), so a Patchbook folder can be copied to
another computer as it is:

    data/
      config.json          Patchbook's own settings (look, theme, panels, defaults)
      secrets.json         the model key, if the user chose to remember it (this computer only)
      itailor-home/        iTailor's user directory: model config, lessons, environment cache
      projects/            the projects (each one an iTailor project folder)

iTailor must learn its home before it is imported anywhere, which is why this
module sets ``ITAILOR_HOME`` at import time.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time

VERSION = "3.0260901"
APP_NAME = "Patchbook"
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.abspath(os.environ.get("PATCHBOOK_HOME") or os.path.join(APP_DIR, "data"))
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
SECRETS_PATH = os.path.join(DATA_DIR, "secrets.json")
ITAILOR_HOME = os.path.join(DATA_DIR, "itailor-home")
DEFAULT_PROJECTS_DIR = os.path.join(DATA_DIR, "projects")
PLUGINS_DIR = os.path.join(APP_DIR, "plugins")
API_KEY_ENV = "PATCHBOOK_API_KEY"

os.makedirs(ITAILOR_HOME, exist_ok=True)
os.environ.setdefault("ITAILOR_HOME", ITAILOR_HOME)
# iTailor keeps its user files in <ITAILOR_HOME>/.itailor (config.json, lessons.jsonl, env.json, ...).
ITAILOR_USER_DIR = os.path.join(os.environ["ITAILOR_HOME"], ".itailor")

LOOKS = ("simple", "professional")
THEMES = ("system", "light", "dark")
PERMISSION_PRESETS = {
    # preset -> iTailor permission mode
    "ask": "default",
    "edits": "acceptEdits",
    "plan": "plan",
    "all": "bypassPermissions",
}
PANEL_DEFAULTS = {
    "simple": {"files": True, "progress": True, "outline": False, "events": False},
    "professional": {"files": True, "outline": True, "progress": True, "events": True},
}
DEFAULTS: dict = {
    "version": VERSION,
    "setupDone": False,
    "userName": "",
    "look": "simple",
    "theme": "system",
    "autosave": True,
    "openLastProject": True,
    "lastProjectId": "",
    "projectsDir": "",
    "externalProjects": [],
    "cellDefaults": {"engine": "quick", "language": "auto", "showCode": False, "effort": "normal"},
    "permissionPreset": "ask",
    "autonomy": "ask",            # ask: every question is shown with a recommendation; auto: clear cases are answered for you
    "layout": {
        "simple": {"panels": dict(PANEL_DEFAULTS["simple"]), "left": 260, "right": 360},
        "professional": {"panels": dict(PANEL_DEFAULTS["professional"]), "left": 280, "right": 400},
    },
    "disabledPlugins": [],
    "effortOverrides": {},
    "eventsShowAll": False,
    "setupAt": "",
    "updatedAt": "",
}

_LOCK = threading.RLock()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_json(path: str, data: dict, private: bool = False) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, path)
    if private:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def _deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# Patchbook's own configuration
# ---------------------------------------------------------------------------
def load() -> dict:
    """Defaults merged with ``config.json``; always complete, always valid."""
    with _LOCK:
        stored = _read_json(CONFIG_PATH) or {}
        cfg = _deep_merge(json.loads(json.dumps(DEFAULTS)), stored)
    cfg["version"] = VERSION
    if cfg.get("look") not in LOOKS:
        cfg["look"] = "simple"
    if cfg.get("theme") not in THEMES:
        cfg["theme"] = "system"
    if cfg.get("permissionPreset") not in PERMISSION_PRESETS:
        cfg["permissionPreset"] = "ask"
    if cfg.get("autonomy") not in ("ask", "auto"):
        cfg["autonomy"] = "ask"
    for look in LOOKS:
        panels = cfg["layout"].setdefault(look, {}).setdefault("panels", {})
        for name, default in PANEL_DEFAULTS[look].items():
            panels.setdefault(name, default)
    cfg["setupDone"] = bool(cfg.get("setupDone"))
    return cfg


def save(patch: dict) -> dict:
    """Merge ``patch`` into ``config.json`` (nested dictionaries merge) and return the result."""
    with _LOCK:
        stored = _read_json(CONFIG_PATH) or {}
        merged = _deep_merge(stored, patch or {})
        merged["version"] = VERSION
        merged["updatedAt"] = now_iso()
        _write_json(CONFIG_PATH, merged)
    return load()


def projects_dir(cfg: dict | None = None) -> str:
    cfg = cfg or load()
    path = str(cfg.get("projectsDir") or "").strip()
    path = os.path.abspath(os.path.expanduser(path)) if path else DEFAULT_PROJECTS_DIR
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Secrets (the model key)
# ---------------------------------------------------------------------------
def secrets_load() -> dict:
    """Put remembered secrets into the process environment (never overriding one already set)."""
    data = _read_json(SECRETS_PATH) or {}
    for name, value in data.items():
        if isinstance(value, str) and value and not os.environ.get(name):
            os.environ[name] = value
    return data


def secret_set(name: str, value: str, remember: bool = True) -> None:
    os.environ[name] = value
    with _LOCK:
        data = _read_json(SECRETS_PATH) or {}
        if remember:
            data[name] = value
        else:
            data.pop(name, None)
        if data:
            _write_json(SECRETS_PATH, data, private=True)
        elif os.path.exists(SECRETS_PATH):
            os.remove(SECRETS_PATH)


def secret_forget(name: str) -> None:
    os.environ.pop(name, None)
    with _LOCK:
        data = _read_json(SECRETS_PATH) or {}
        data.pop(name, None)
        if data:
            _write_json(SECRETS_PATH, data, private=True)
        elif os.path.exists(SECRETS_PATH):
            os.remove(SECRETS_PATH)


def secret_present(name: str) -> bool:
    return bool(os.environ.get(name))


def secret_remembered(name: str) -> bool:
    return bool((_read_json(SECRETS_PATH) or {}).get(name))


# ---------------------------------------------------------------------------
# iTailor's user-level settings (model, permissions) live in ITAILOR_HOME/config.json
# ---------------------------------------------------------------------------
def itailor_settings() -> dict:
    from itailor import settings as settings_module
    return settings_module.load(None)


def itailor_user_layer() -> dict:
    from itailor import settings as settings_module
    raw = settings_module.read_json(settings_module.user_config_path())
    return raw if isinstance(raw, dict) and "__error" not in raw else {}


def write_itailor_user(patch: dict) -> dict:
    from itailor import settings as settings_module
    return settings_module.write_layer(settings_module.user_config_path(), patch)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------
def reset(scope: str = "settings", delete_projects: bool = False) -> dict:
    """``settings``: Patchbook settings, the remembered key and iTailor's model
    configuration go back to defaults. ``everything``: additionally iTailor's
    home (lessons, environment cache, model capability cache) and, if asked,
    every project in the default projects folder."""
    removed: list[str] = []

    def rm(path: str) -> None:
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
                removed.append(path)
            elif os.path.exists(path):
                os.remove(path)
                removed.append(path)
        except OSError as exc:
            removed.append(f"{path} (could not remove: {exc})")

    with _LOCK:
        cfg = load()
        rm(CONFIG_PATH)
        rm(SECRETS_PATH)
        rm(os.path.join(ITAILOR_USER_DIR, "config.json"))
        os.environ.pop(API_KEY_ENV, None)
        if scope == "everything":
            rm(ITAILOR_USER_DIR)
            os.makedirs(ITAILOR_USER_DIR, exist_ok=True)
            if delete_projects:
                rm(projects_dir(cfg))
                os.makedirs(DEFAULT_PROJECTS_DIR, exist_ok=True)
    return {"scope": scope, "deletedProjects": bool(delete_projects and scope == "everything"), "removed": removed}
