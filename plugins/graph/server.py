# Patchbook plugin: Project graph - Copyright (c) 2026 Michael Bidollahkhani. MIT License.
"""The project knowledge graph (.itailor/graph.yaml): as the model sees it, and as YAML."""

from __future__ import annotations

import os

from flask import jsonify, request

from itailor.graph import ProjectGraph, graph_path


def register(api):
    @api.route("/<pid>", methods=["GET"])
    def graph(pid):
        project = api.project_path(pid)
        path = graph_path(project)
        if request.args.get("rebuild") == "1":
            g = ProjectGraph(path)
            g.rebuild(project)
            g.save()
        g = ProjectGraph(path)
        text = ""
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        return jsonify({"summary": g.summary(max_runs=10, max_files=40, max_decisions=20), "yaml": text,
                        "nodes": len(g.nodes), "edges": len(g.edges), "path": path})
