# Patchbook plugin: Lessons - Copyright (c) 2026 Michael Bidollahkhani. MIT License.
"""Lessons iTailor remembered for a project (and for the user), with the rules it proposes."""

from __future__ import annotations

from flask import jsonify

import itailor


def register(api):
    @api.route("/<pid>", methods=["GET"])
    def lessons(pid):
        project = api.project_path(pid)
        agent = itailor.Agent(project, discover_env=False)
        return jsonify({"lessons": [dict(l.to_dict(), confidence=l.confidence) for l in agent.lessons.all()],
                        "proposals": agent.lessons.propose_rules()})

    @api.route("/<pid>/<lesson_id>", methods=["DELETE"])
    def forget(pid, lesson_id):
        project = api.project_path(pid)
        agent = itailor.Agent(project, discover_env=False)
        return jsonify({"ok": agent.lessons.forget(lesson_id)})
