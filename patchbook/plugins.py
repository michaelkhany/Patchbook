# Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
Plugins: folders under ``plugins/`` that add a panel, a tool or a section.

    plugins/<id>/
      plugin.json      the manifest (below)
      server.py        optional: ``def register(api)`` adds routes under /api/plugins/<id>/
      client.js        optional: loaded in the browser after boot; registers with Patchbook.plugins

Manifest fields:
    id, name, version, description     identity and the sentence shown on the startup screen
    kind                               "panel" (a dockable panel), "tool" (an entry in the Tools menu), "section"
    icon                               a name from static/js/icons.js
    looks                              ["simple", "professional"]: in which looks it is offered
    dock                               "left" | "right" | "bottom" for panels
    order                              sort key (lower first)
    server, client                     file names (optional)

A plugin that fails to load is reported on the startup screen and skipped; it
never stops Patchbook from starting.
"""

from __future__ import annotations

import importlib.util
import json
import os
import traceback
from dataclasses import asdict, dataclass, field

from flask import Blueprint

from . import config

KINDS = ("panel", "tool", "section")


@dataclass
class Plugin:
    id: str
    name: str
    version: str = "1.0"
    description: str = ""
    kind: str = "panel"
    icon: str = "box"
    looks: list = field(default_factory=lambda: ["simple", "professional"])
    dock: str = "right"
    order: int = 100
    server: str = ""
    client: str = ""
    path: str = ""
    status: str = "pending"      # loaded | disabled | error
    error: str = ""
    error_detail: str = ""
    routes: int = 0

    def public(self) -> dict:
        data = asdict(self)
        data.pop("error_detail", None)
        data["clientUrl"] = f"/plugins/{self.id}/{self.client}" if self.client and self.status == "loaded" else ""
        return data


class PluginAPI:
    """What ``register(api)`` receives: a way to add routes plus Patchbook's services."""

    def __init__(self, plugin: Plugin, services: dict) -> None:
        self.plugin = plugin
        self.blueprint = Blueprint(f"plugin_{plugin.id}", f"plugin_{plugin.id}", url_prefix=f"/api/plugins/{plugin.id}")
        self.services = services
        self.config = services["config"]
        self.projects = services["projects"]
        self.runs = services["runs"]
        self.app_dir = config.APP_DIR
        self.plugin_dir = plugin.path

    def route(self, rule: str, **options):
        def decorator(fn):
            self.plugin.routes += 1
            return self.blueprint.route(rule, **options)(fn)
        return decorator

    def project_path(self, project_id: str) -> str:
        return self.projects.project_path(project_id)


def _read_manifest(folder: str) -> Plugin | None:
    manifest = os.path.join(folder, "plugin.json")
    if not os.path.isfile(manifest):
        return None
    with open(manifest, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    pid = str(data.get("id") or os.path.basename(folder))
    if not pid.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"invalid plugin id {pid!r}")
    plugin = Plugin(id=pid, name=str(data.get("name") or pid), version=str(data.get("version") or "1.0"),
                    description=str(data.get("description") or ""), kind=str(data.get("kind") or "panel"),
                    icon=str(data.get("icon") or "box"), looks=[str(x) for x in (data.get("looks") or ["simple", "professional"])],
                    dock=str(data.get("dock") or "right"), order=int(data.get("order") or 100),
                    server=str(data.get("server") or ""), client=str(data.get("client") or ""), path=folder)
    if plugin.kind not in KINDS:
        raise ValueError(f"plugin {pid}: kind must be one of {KINDS}")
    for name in (plugin.server, plugin.client):
        if name and (os.sep in name or "/" in name or not os.path.isfile(os.path.join(folder, name))):
            raise ValueError(f"plugin {pid}: file not found: {name}")
    return plugin


def load_plugins(app, services: dict) -> list[Plugin]:
    plugins: list[Plugin] = []
    if not os.path.isdir(config.PLUGINS_DIR):
        return plugins
    disabled = set(config.load().get("disabledPlugins") or [])
    for name in sorted(os.listdir(config.PLUGINS_DIR)):
        folder = os.path.join(config.PLUGINS_DIR, name)
        if not os.path.isdir(folder) or name.startswith((".", "_")):
            continue
        try:
            plugin = _read_manifest(folder)
        except Exception as exc:  # noqa: BLE001 - a broken manifest is reported, not fatal
            plugins.append(Plugin(id=name, name=name, path=folder, status="error", error=f"{type(exc).__name__}: {exc}"))
            continue
        if plugin is None:
            continue
        if plugin.id in disabled:
            plugin.status = "disabled"
            plugins.append(plugin)
            continue
        try:
            if plugin.server:
                spec = importlib.util.spec_from_file_location(f"patchbook_plugin_{plugin.id}", os.path.join(folder, plugin.server))
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                api = PluginAPI(plugin, services)
                register = getattr(module, "register", None)
                if callable(register):
                    register(api)
                app.register_blueprint(api.blueprint)
            plugin.status = "loaded"
        except Exception as exc:  # noqa: BLE001
            plugin.status = "error"
            plugin.error = f"{type(exc).__name__}: {exc}"
            plugin.error_detail = traceback.format_exc()
        plugins.append(plugin)
    plugins.sort(key=lambda p: (p.order, p.name.lower()))
    return plugins
