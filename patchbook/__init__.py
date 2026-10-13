# Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
Patchbook: a notebook where you write what you want in plain language and
iTailor writes the code, runs it on this computer, reads the real result,
repairs what breaks and shows you what it found.

This package is the Flask application. ``create_app()`` wires the API, loads
the plugins and starts the background discovery of this machine.
"""

from __future__ import annotations

import os
import time

from flask import Flask, jsonify, render_template, request, send_from_directory

from . import config  # noqa: F401 - sets ITAILOR_HOME before itailor is imported

VERSION = config.VERSION
APP_NAME = config.APP_NAME


def create_app() -> Flask:
    config.secrets_load()
    import itailor  # noqa: E402 - after ITAILOR_HOME is set
    from . import api_projects, api_runs, api_system, projects
    from .plugins import load_plugins
    from .runs import Busy, RunManager

    app = Flask(__name__, static_folder=os.path.join(config.APP_DIR, "static"), static_url_path="/static",
                template_folder=os.path.join(config.APP_DIR, "templates"))
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024
    app.config["JSON_SORT_KEYS"] = False
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    from . import strategy

    manager = RunManager()
    services = {"config": config, "projects": projects, "runs": manager, "itailor": itailor}
    app.extensions["patchbook"] = {"runs": manager, "services": services, "plugins": [], "started": time.time(),
                                   "libraryWarnings": strategy.library_self_check()}
    for warning in app.extensions["patchbook"]["libraryWarnings"]:
        print("Patchbook warning:", warning)

    app.register_blueprint(api_system.bp)
    app.register_blueprint(api_projects.bp)
    app.register_blueprint(api_runs.bp)
    app.extensions["patchbook"]["plugins"] = load_plugins(app, services)

    @app.get("/")
    def index():
        return render_template("index.html", version=VERSION, app_name=APP_NAME)

    @app.get("/plugins/<pid>/<path:filename>")
    def plugin_asset(pid, filename):
        plugin = next((p for p in app.extensions["patchbook"]["plugins"] if p.id == pid and p.status == "loaded"), None)
        if plugin is None or filename.endswith(".py") or filename == "plugin.json":
            return jsonify({"error": "not found"}), 404
        return send_from_directory(plugin.path, filename, conditional=True)

    @app.errorhandler(projects.NotFound)
    def not_found(exc):
        return jsonify({"error": str(exc)}), 404

    @app.errorhandler(projects.Invalid)
    def invalid(exc):
        return jsonify({"error": str(exc)}), 400

    @app.errorhandler(Busy)
    def busy(exc):
        return jsonify({"error": str(exc)}), 409

    @app.errorhandler(404)
    def http_404(exc):
        if request.path.startswith("/api/"):
            return jsonify({"error": "not found"}), 404
        return render_template("index.html", version=VERSION, app_name=APP_NAME), 404

    @app.errorhandler(500)
    def http_500(exc):
        return jsonify({"error": "Patchbook hit an internal error. The terminal window shows the details."}), 500

    @app.after_request
    def no_cache_for_api(response):
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    api_system.start_env_discovery()
    return app
