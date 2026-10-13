# Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""Boot, configuration, first-run setup, model and environment, reset."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
import time

from flask import Blueprint, current_app, jsonify, request

import itailor
from itailor import env as env_module, languages as languages_module
from itailor.llm import discover as llm_discover, providers, select as llm_select
from itailor.llm.client import ModelConfig, OpenAICompatibleClient

from . import config, projects, strategy

bp = Blueprint("system", __name__)

SECTIONS = [
    {"id": "projects", "name": "Project manager", "description": "Create, open, rename, duplicate and delete projects."},
    {"id": "patchbook", "name": "Patchbook editor", "description": "The notebook: patches in plain language, their code, output and files."},
    {"id": "files", "name": "Files", "description": "The files in the project folder; add, preview, download."},
    {"id": "progress", "name": "Progress", "description": "What iTailor is doing right now, in plain language."},
    {"id": "outline", "name": "Outline", "description": "All cells of the open Patchbook at a glance.", "looks": ["professional"]},
    {"id": "events", "name": "Events", "description": "Every event of the current run, with its details.", "looks": ["professional"]},
    {"id": "settings", "name": "Settings", "description": "Look, model, permissions, panels and reset."},
]

_ENV: dict = {"status": "idle", "summary": "", "manifest": None, "error": "", "started": 0.0, "finished": 0.0}
_ENV_LOCK = threading.Lock()
_MODEL_CACHE: dict = {"at": 0.0, "value": None}
_LIST_CACHE: dict = {}      # base URL -> {"at": time, "value": the listed models}


# ---------------------------------------------------------------------------
# Environment discovery (runs in the background at start-up)
# ---------------------------------------------------------------------------
def start_env_discovery(refresh: bool = False) -> None:
    with _ENV_LOCK:
        if _ENV["status"] == "running":
            return
        _ENV.update({"status": "running", "error": "", "started": time.time()})

    def worker() -> None:
        try:
            manifest = env_module.discover(None, refresh=refresh, ttl_hours=24.0, include_apps=True)
            _ENV["manifest"] = manifest
            _ENV["summary"] = env_module.summary(manifest, max_apps=30)
            _ENV["status"] = "ready"
        except Exception as exc:  # noqa: BLE001
            _ENV["status"] = "error"
            _ENV["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            _ENV["finished"] = time.time()

    threading.Thread(target=worker, daemon=True, name="patchbook-env").start()


def env_public(full: bool = False) -> dict:
    manifest = _ENV.get("manifest") or {}
    data = {"status": _ENV["status"], "summary": _ENV["summary"], "error": _ENV["error"],
            "cached": bool(manifest.get("cached")), "generatedAt": manifest.get("generatedAt", ""),
            "seconds": round((_ENV["finished"] or time.time()) - _ENV["started"], 1) if _ENV["started"] else 0}
    if full:
        data["manifest"] = manifest
    return data


# ---------------------------------------------------------------------------
# Model status
# ---------------------------------------------------------------------------
def model_status(force: bool = False) -> dict:
    now = time.time()
    if not force and _MODEL_CACHE["value"] and now - _MODEL_CACHE["at"] < 60:
        return _MODEL_CACHE["value"]
    settings = config.itailor_settings()
    base = str(settings.get("baseUrl") or "")
    key_env = str(settings.get("apiKeyEnv") or "")
    key_set = bool(os.environ.get(key_env)) if key_env else False
    model = str(settings.get("model") or "auto")
    status = {"configured": False, "source": "none", "baseUrl": base, "model": model, "keySet": key_set, "keyEnv": key_env,
              "keyRemembered": config.secret_remembered(config.API_KEY_ENV), "label": "No model connected",
              "localOnly": bool((settings.get("privacy") or {}).get("localOnly")), "provider": ""}
    if base:
        local = providers.is_local(base)
        status["provider"] = providers.detect(base)
        if key_set or local:
            status.update({"configured": True, "source": "settings",
                           "label": f"{model if model != 'auto' else 'automatic choice'} at {base}"})
        else:
            status["label"] = "A model address is set but no key is stored"
    else:
        try:
            local = [s for s in llm_discover.from_local_servers(timeout=1.0) if s.models]
        except Exception:  # noqa: BLE001
            local = []
        if local:
            status.update({"configured": True, "source": "local-server", "baseUrl": local[0].base_url,
                           "label": f"{local[0].note} ({len(local[0].models)} model(s))", "provider": local[0].provider})
    status["demo"] = not status["configured"]
    _MODEL_CACHE.update({"at": now, "value": status})
    return status


def _public_itailor_settings() -> dict:
    s = config.itailor_settings()
    keys = ("baseUrl", "model", "apiKeyEnv", "permissionMode", "profile", "toolCalling", "streaming", "webSearch",
            "permissions", "sandbox", "budgets", "privacy", "approvePlans", "modelBandit", "discoverApps",
            "maxIterations", "runTimeoutSeconds", "modelTimeoutSeconds", "permissionTimeoutSeconds", "maxTokens", "temperature")
    out = {k: s.get(k) for k in keys}
    out["apiKeySet"] = bool(os.environ.get(s.get("apiKeyEnv") or config.API_KEY_ENV))
    out["apiKeyRemembered"] = config.secret_remembered(config.API_KEY_ENV)
    out["sources"] = s.get("_sources")
    out["errors"] = s.get("_errors")
    out["userConfigPath"] = os.path.join(config.ITAILOR_USER_DIR, "config.json")
    preset = next((p for p, mode in config.PERMISSION_PRESETS.items() if mode == s.get("permissionMode")), "ask")
    out["permissionPreset"] = preset
    return out


def _apply_model(body: dict) -> None:
    """Shared by setup and settings: base URL, key, model, where the key lives."""
    base = str(body.get("baseUrl") or "").strip().rstrip("/")
    model = str(body.get("model") or "").strip() or "auto"
    api_key = str(body.get("apiKey") or "").strip()
    remember = bool(body.get("remember", True))
    patch: dict = {"baseUrl": base, "model": model}
    if api_key:
        config.secret_set(config.API_KEY_ENV, api_key, remember=remember)
        patch["apiKeyEnv"] = config.API_KEY_ENV
    elif base and providers.is_local(base) and not config.secret_present(config.API_KEY_ENV):
        # A local server needs no key; iTailor still wants a non-empty one to consider the source usable.
        config.secret_set(config.API_KEY_ENV, "local", remember=remember)
        patch["apiKeyEnv"] = config.API_KEY_ENV
    elif base:
        patch["apiKeyEnv"] = config.API_KEY_ENV
    else:
        patch["apiKeyEnv"] = ""
    if body.get("forgetKey"):
        config.secret_forget(config.API_KEY_ENV)
    config.write_itailor_user(patch)
    _MODEL_CACHE["value"] = None
    _LIST_CACHE.clear()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@bp.get("/api/boot")
def api_boot():
    state = current_app.extensions["patchbook"]
    cfg = config.load()
    plugins = [p.public() for p in state["plugins"]]
    warnings = list(state.get("libraryWarnings") or [])
    projects_dir = config.projects_dir(cfg)
    if sys.platform.startswith("win") and len(projects_dir) > 150:
        warnings.append(f"The projects folder path is long ({len(projects_dir)} characters). Windows limits paths to 260 characters "
                        "unless long paths are enabled, and iTailor creates deep run folders inside each project. "
                        "Move Patchbook to a shorter path (for example C:\\Patchbook) or choose a shorter projects folder in Settings.")
    return jsonify({
        "warnings": warnings,
        "app": {"name": config.APP_NAME, "version": config.VERSION, "dir": config.APP_DIR, "dataDir": config.DATA_DIR,
                "projectsDir": config.projects_dir(cfg), "startedAt": state["started"]},
        "library": {"version": itailor.__version__, "path": os.path.dirname(os.path.abspath(itailor.__file__))},
        "python": sys.version.split()[0], "platform": f"{platform.system()} {platform.release()}",
        "setupDone": cfg["setupDone"], "config": cfg,
        "plugins": plugins,
        "sections": SECTIONS,
        "tools": [p for p in plugins if p["kind"] == "tool"],
        "env": env_public(), "model": model_status(),
        "languages": languages_module.available(),
        "efforts": strategy.public(cfg.get("effortOverrides") if isinstance(cfg.get("effortOverrides"), dict) else None),
        "permissionPresets": [
            {"id": "ask", "name": "Ask me before anything consequential", "description": "Reading files and running code in the project is allowed; installing packages, commands that change things, and network access pause and ask you. Recommended."},
            {"id": "edits", "name": "Allow file changes without asking", "description": "Like the first option, but creating and editing files in the project never asks."},
            {"id": "plan", "name": "Read only", "description": "iTailor may read and plan but cannot write files or run commands. Useful to see what it would do."},
            {"id": "all", "name": "Allow everything", "description": "Nothing asks. Only for a folder you can afford to lose. (Professional look only.)"},
        ],
        "activeRuns": state["runs"].active(),
    })


@bp.get("/api/config")
def api_config_get():
    return jsonify(config.load())


@bp.post("/api/config")
def api_config_post():
    body = request.get_json(force=True, silent=True) or {}
    allowed = ("userName", "look", "theme", "autosave", "openLastProject", "lastProjectId", "projectsDir", "cellDefaults",
               "layout", "disabledPlugins", "eventsShowAll", "permissionPreset", "setupDone", "effortOverrides", "autonomy")
    patch = {k: body[k] for k in allowed if k in body}
    if "look" in patch and patch["look"] not in config.LOOKS:
        patch.pop("look")
    if "theme" in patch and patch["theme"] not in config.THEMES:
        patch.pop("theme")
    if "permissionPreset" in patch:
        if patch["permissionPreset"] not in config.PERMISSION_PRESETS:
            patch.pop("permissionPreset")
        else:
            config.write_itailor_user({"permissionMode": config.PERMISSION_PRESETS[patch["permissionPreset"]]})
    return jsonify(config.save(patch))


@bp.post("/api/setup")
def api_setup():
    """The first-run wizard, saved in one go."""
    body = request.get_json(force=True, silent=True) or {}
    look = body.get("look") if body.get("look") in config.LOOKS else "simple"
    theme = body.get("theme") if body.get("theme") in config.THEMES else "system"
    preset = body.get("permissionPreset") if body.get("permissionPreset") in config.PERMISSION_PRESETS else "ask"
    projects_dir = str(body.get("projectsDir") or "").strip()
    if projects_dir:
        projects_dir = os.path.abspath(os.path.expanduser(projects_dir))
        try:
            os.makedirs(projects_dir, exist_ok=True)
        except OSError as exc:
            return jsonify({"error": f"The projects folder cannot be created: {exc}"}), 400
    model = body.get("model") if isinstance(body.get("model"), dict) else {}
    mode = str(model.get("mode") or "demo")
    if mode in ("found", "hosted") and model.get("baseUrl"):
        _apply_model(model)
    else:
        config.write_itailor_user({"baseUrl": "", "model": "auto", "apiKeyEnv": ""})
        _MODEL_CACHE["value"] = None
    config.write_itailor_user({"permissionMode": config.PERMISSION_PRESETS[preset]})
    cfg = config.save({"setupDone": True, "setupAt": config.now_iso(), "userName": str(body.get("userName") or "").strip()[:80],
                       "look": look, "theme": theme, "permissionPreset": preset,
                       "projectsDir": "" if projects_dir == config.DEFAULT_PROJECTS_DIR else projects_dir})
    sample = None
    if body.get("createSample"):
        try:
            sample = projects.create_sample_project()
            cfg = config.save({"lastProjectId": sample["id"]})
        except Exception as exc:  # noqa: BLE001
            sample = {"error": f"{type(exc).__name__}: {exc}"}
    return jsonify({"ok": True, "config": cfg, "model": model_status(force=True), "sample": sample})


@bp.get("/api/env")
def api_env():
    if request.args.get("refresh") == "1" and _ENV["status"] != "running":
        start_env_discovery(refresh=True)
    return jsonify(env_public(full=request.args.get("full") == "1"))


@bp.get("/api/env/find")
def api_env_find():
    name = request.args.get("name", "")
    return jsonify({"program": env_module.find_program(name), "app": env_module.find_app(name, _ENV.get("manifest") or None)})


@bp.get("/api/models/status")
def api_models_status():
    return jsonify(model_status(force=request.args.get("refresh") == "1"))


@bp.get("/api/models/list")
def api_models_list():
    """The models the configured service offers (or the local server found), for the Settings selection."""
    status = model_status(force=request.args.get("refresh") == "1")
    base = str(status.get("baseUrl") or "")
    current = str(status.get("model") or "auto")
    if not base:
        return jsonify({"ok": False, "baseUrl": "", "models": [], "contexts": {}, "current": current,
                        "message": "No model service is set. Connect one above, or start a local server."})
    cached = _LIST_CACHE.get(base)
    if cached and request.args.get("refresh") != "1" and time.time() - cached["at"] < 120:
        return jsonify({**cached["value"], "current": current})
    settings = config.itailor_settings()
    key_env = settings.get("apiKeyEnv") or config.API_KEY_ENV
    api_key = os.environ.get(key_env, "") or ("local" if providers.is_local(base) else "")
    listed = OpenAICompatibleClient(ModelConfig(base_url=base, api_key=api_key, timeout=20)).list_models(timeout=15)
    value = {"ok": bool(listed.get("ok")), "baseUrl": base, "models": providers.filter_models(base, listed.get("models") or []),
             "contexts": listed.get("contexts") or {}, "message": listed.get("message", ""), "provider": providers.detect(base)}
    _LIST_CACHE[base] = {"at": time.time(), "value": value}
    return jsonify({**value, "current": current})


@bp.get("/api/models/discover")
def api_models_discover():
    sources = llm_discover.discover(None)
    s = config.itailor_settings()
    if s.get("baseUrl"):
        key_env = s.get("apiKeyEnv") or config.API_KEY_ENV
        sources.insert(0, llm_discover.Source(id="settings", kind="config", base_url=s["baseUrl"], api_key=os.environ.get(key_env, ""),
                                              key_env=key_env, model="" if s.get("model") in ("auto", None) else s.get("model"),
                                              provider=providers.detect(s["baseUrl"]), local=providers.is_local(s["baseUrl"]),
                                              note="from Settings"))
    usable = [x for x in sources if x.base_url and (x.api_key or x.local)]
    llm_discover.fill_models(usable, timeout=12)
    machine = env_module.machine_for_selection(_ENV.get("manifest") or None)
    candidates = llm_select.candidates_from_sources(usable, {}, machine)
    privacy = s.get("privacy") or {}
    selection = llm_select.select(candidates, llm_select.TaskProfile(),
                                  llm_select.Constraints(local_only=bool(privacy.get("localOnly")), exclude=s.get("autoModelExclude") or []))
    return jsonify({"sources": [x.public() for x in sources], "selection": selection.to_dict(),
                    "catalog": providers.catalog()})


@bp.post("/api/models/test")
def api_models_test():
    body = request.get_json(force=True, silent=True) or {}
    base = str(body.get("baseUrl") or "").strip().rstrip("/")
    if not base:
        return jsonify({"ok": False, "message": "Enter the address of the model service first."}), 400
    api_key = str(body.get("apiKey") or "").strip() or os.environ.get(config.API_KEY_ENV, "") or ("local" if providers.is_local(base) else "")
    model = str(body.get("model") or "").strip()
    started = time.time()
    client = OpenAICompatibleClient(ModelConfig(base_url=base, api_key=api_key, model=model, timeout=30))
    listed = client.list_models(timeout=20)
    models = providers.filter_models(base, listed.get("models") or [])
    out = {"ok": bool(listed.get("ok")), "message": listed.get("message", ""), "models": models[:200],
           "provider": providers.detect(base), "local": providers.is_local(base), "ms": int((time.time() - started) * 1000)}
    if model and (listed.get("ok") or not models):
        try:
            reply = client.chat([{"role": "user", "content": "Reply with the single word OK."}], max_tokens=8, stream=False)
            out["chat"] = {"ok": bool(reply.ok), "text": (reply.text or "")[:80], "error": reply.error or ""}
            out["ok"] = out["ok"] or bool(reply.ok)
            if reply.ok and not out["message"]:
                out["message"] = "The model answered."
        except Exception as exc:  # noqa: BLE001
            out["chat"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if not out["ok"] and not out["message"]:
        out["message"] = "No answer from that address."
    return jsonify(out)


@bp.get("/api/settings/itailor")
def api_itailor_settings_get():
    return jsonify(_public_itailor_settings())


@bp.post("/api/settings/itailor")
def api_itailor_settings_post():
    body = request.get_json(force=True, silent=True) or {}
    if any(k in body for k in ("baseUrl", "model", "apiKey", "forgetKey")):
        current = config.itailor_user_layer()
        _apply_model({"baseUrl": body.get("baseUrl", current.get("baseUrl", "")), "model": body.get("model", current.get("model", "auto")),
                      "apiKey": body.get("apiKey", ""), "remember": body.get("remember", True), "forgetKey": body.get("forgetKey")})
    patch: dict = {}
    if body.get("permissionPreset") in config.PERMISSION_PRESETS:
        patch["permissionMode"] = config.PERMISSION_PRESETS[body["permissionPreset"]]
        config.save({"permissionPreset": body["permissionPreset"]})
    elif body.get("permissionMode") in ("default", "acceptEdits", "plan", "bypassPermissions"):
        patch["permissionMode"] = body["permissionMode"]
    for key in ("toolCalling", "webSearch", "approvePlans", "discoverApps", "streaming", "profile"):
        if key in body:
            patch[key] = body[key]
    for key in ("maxIterations", "runTimeoutSeconds", "modelTimeoutSeconds", "permissionTimeoutSeconds", "maxTokens"):
        if key in body:
            try:
                patch[key] = int(body[key])
            except (TypeError, ValueError):
                pass
    if "temperature" in body:
        try:
            patch["temperature"] = float(body["temperature"])
        except (TypeError, ValueError):
            pass
    if "sandboxMode" in body:
        patch["sandbox"] = {**(config.itailor_user_layer().get("sandbox") or {}), "mode": str(body["sandboxMode"] or "")}
    if "localOnly" in body:
        patch["privacy"] = {**(config.itailor_user_layer().get("privacy") or {}), "localOnly": bool(body["localOnly"])}
    if isinstance(body.get("budgets"), dict):
        budgets = {}
        for key in ("steps", "repairsPerStep", "replans", "minutes", "toolStepsPerStep"):
            if key in body["budgets"]:
                try:
                    budgets[key] = float(body["budgets"][key]) if key == "minutes" else int(body["budgets"][key])
                except (TypeError, ValueError):
                    pass
        if budgets:
            patch["budgets"] = {**(config.itailor_user_layer().get("budgets") or {}), **budgets}
    if patch:
        config.write_itailor_user(patch)
    _MODEL_CACHE["value"] = None
    return jsonify(_public_itailor_settings())


@bp.post("/api/reset")
def api_reset():
    body = request.get_json(force=True, silent=True) or {}
    scope = "everything" if body.get("scope") == "everything" else "settings"
    state = current_app.extensions["patchbook"]
    if state["runs"].active():
        return jsonify({"error": "A patch is still running. Stop it before resetting."}), 409
    result = config.reset(scope, delete_projects=bool(body.get("deleteProjects")))
    _MODEL_CACHE["value"] = None
    return jsonify({"ok": True, **result, "config": config.load()})


@bp.get("/api/plugins")
def api_plugins():
    state = current_app.extensions["patchbook"]
    return jsonify({"plugins": [p.public() for p in state["plugins"]]})


@bp.post("/api/open-folder")
def api_open_folder():
    """Show a folder in the file manager of this computer. Only folders Patchbook knows."""
    body = request.get_json(force=True, silent=True) or {}
    path = os.path.abspath(str(body.get("path") or ""))
    allowed = [config.DATA_DIR, config.projects_dir()] + [p["path"] for p in projects.list_projects()]
    if not any(os.path.commonpath([root, path]) == root for root in allowed if os.path.isdir(root)) or not os.path.isdir(path):
        return jsonify({"error": "That folder is not one Patchbook manages."}), 400
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Could not open the folder: {exc}", "path": path}), 500
    return jsonify({"ok": True, "path": path})
