# Patchbook plugin: Activity - Copyright (c) 2026 Michael Bidollahkhani. MIT License.
"""The activity record of a project (.patchbook/activity.jsonl): what every run used."""

from __future__ import annotations

from flask import jsonify, request

from patchbook import activity


def register(api):
    @api.route("/<pid>", methods=["GET"])
    def records(pid):
        project = api.project_path(pid)
        return jsonify({"records": activity.load(project, limit=int(request.args.get("limit") or 100)), "path": activity.path(project)})
