# Patchbook plugin: Shared store - Copyright (c) 2026 Michael Bidollahkhani. MIT License.
"""The registry of the project's shared/ folder: values, parameters and methods patches left for each other."""

from __future__ import annotations

from flask import jsonify, request

from patchbook import shared_store


def register(api):
    @api.route("/<pid>", methods=["GET"])
    def registry(pid):
        project = api.project_path(pid)
        data = shared_store.sync(project) if request.args.get("scan") == "1" else shared_store.load(project)
        return jsonify({"registry": data, "folder": shared_store.STORE_DIR, "path": shared_store.store_dir(project),
                        "prompt": shared_store.prompt_block(project)})
