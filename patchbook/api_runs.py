# Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""Starting, following, answering and stopping runs; the run history of a project."""

from __future__ import annotations

import os

from flask import Blueprint, Response, current_app, jsonify, request

from itailor.runs import RunDir, list_runs
from itailor.transcript import Transcript

from . import config, projects, recommend, strategy
from .api_system import model_status
from .runs import build_context

bp = Blueprint("runs", __name__)


def _manager():
    return current_app.extensions["patchbook"]["runs"]


@bp.post("/api/projects/<pid>/patchbooks/<nid>/cells/<cid>/run")
def api_run_cell(pid, nid, cid):
    body = request.get_json(force=True, silent=True) or {}
    project = projects.project_path(pid)
    book = projects.get_patchbook(pid, nid)
    cell = next((c for c in book["cells"] if c["id"] == cid), None)
    if cell is None:
        return jsonify({"error": "no such cell"}), 404
    if "text" in body:
        cell["text"] = str(body["text"] or "")
    text = cell["text"].strip()
    if not text:
        return jsonify({"error": "Write what the patch should do first."}), 400
    if cell["kind"] == "note":
        return jsonify({"error": "A note is not run; it only documents."}), 400
    cfg = config.load()
    if cell["kind"] == "code":
        engine = "code"
    else:
        engine = body.get("engine") or cell.get("engine") or book["settings"].get("engine") or cfg["cellDefaults"].get("engine") or "quick"
        if engine not in ("quick", "thorough", "ask"):
            engine = "quick"
    language = body.get("language") or cell.get("language") or book["settings"].get("language") or "auto"
    effort = strategy.normalize(body.get("effort") or cell.get("effort") or book["settings"].get("effort") or cfg["cellDefaults"].get("effort"))
    status = model_status()
    demo = body.get("model") == "demo" or (cell["kind"] != "code" and not status["configured"])
    context, history = build_context(book, cid)
    cell_index = next((i for i, c in enumerate(book["cells"]) if c["id"] == cid), -1) + 1
    # Mark the cell running on disk first, so a reopened page sees it.
    cell.update({"status": "running", "runId": "", "steps": [], "finished": ""})
    projects.save_patchbook(pid, nid, book)
    effort_overrides = cfg.get("effortOverrides") if isinstance(cfg.get("effortOverrides"), dict) else None
    spec = {"projectId": pid, "projectPath": project, "patchbookId": nid, "cellId": cid, "cellIndex": cell_index, "task": text,
            "engine": engine, "effort": effort, "effortOverrides": effort_overrides, "language": language,
            "autonomy": cfg.get("autonomy") or "ask",
            "checks": body.get("checks") or [], "mode": body.get("mode") or None,
            "model": None if demo else (body.get("model") or None), "demo": demo, "context": context, "history": history,
            "code": text if engine == "code" else ""}
    entry = _manager().start(spec)
    projects.update_cell(pid, nid, cid, {"runId": entry["id"]})
    return jsonify({"run": _manager().public(entry), "cellId": cid, "demo": demo, "engine": engine, "effort": effort,
                    "approaches": [strategy.STRATEGIES[s]["label"] for s in strategy.chain_for(engine, effort, effort_overrides)]})


@bp.get("/api/runs/active")
def api_runs_active():
    return jsonify({"runs": _manager().active()})


@bp.get("/api/runs/<rid>")
def api_run_get(rid):
    entry = _manager().get(rid)
    if not entry:
        return jsonify({"error": "no such run"}), 404
    data = _manager().public(entry)
    data["log"] = entry["log"][-500:]
    data["steps"] = entry["steps"]
    return jsonify(data)


@bp.get("/api/runs/<rid>/events")
def api_run_events(rid):
    if not _manager().get(rid):
        return jsonify({"error": "no such run"}), 404
    return Response(_manager().stream(rid), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@bp.post("/api/runs/<rid>/answer")
def api_run_answer(rid):
    """Answer a question. ``remember: true`` with an allow also adds a standing allow rule for this kind of
    action to the project's iTailor settings, in the library's own rule form, so it is not asked again there."""
    body = request.get_json(force=True, silent=True) or {}
    answer = body.get("decision") if body.get("decision") is not None else body.get("answer")
    rule = ""
    entry = _manager().get(rid)
    if body.get("remember") and answer in ("allow", "always") and entry:
        payload = _manager().pending_payload(rid, body.get("requestId", ""))
        rule = recommend.standing_rule(payload or {})
        if rule:
            from itailor import settings as settings_module
            project = projects.project_path(entry["projectId"])
            settings_module.add_permission_rule(settings_module.project_settings_path(project), "allow", rule)
        answer = "always"
    ok = _manager().answer(rid, body.get("requestId", ""), answer)
    return jsonify({"ok": ok, "rule": rule})


@bp.post("/api/runs/<rid>/stop")
def api_run_stop(rid):
    return jsonify({"ok": _manager().stop(rid)})


# ---------------------------------------------------------------------------
# History (what iTailor left under <project>/.itailor/runs/)
# ---------------------------------------------------------------------------
def _cells_by_run(pid: str) -> dict:
    """What Patchbook knows about each iTailor run folder: the cell that produced it."""
    out: dict = {}
    for book in projects.list_patchbooks(pid):
        try:
            full = projects.get_patchbook(pid, book["id"])
        except Exception:  # noqa: BLE001
            continue
        for index, cell in enumerate(full["cells"]):
            result = cell.get("result") or {}
            run_dir = str(result.get("runDir") or "")
            run_id = str(result.get("runId") or "")
            if not run_id and run_dir.startswith(".itailor/runs/"):
                run_id = run_dir.split("/")[2] if len(run_dir.split("/")) > 2 else ""
            if run_id:
                out[run_id] = {"patchbook": book["name"], "patchbookId": book["id"], "cellId": cell["id"], "cellIndex": index + 1,
                               "text": str(cell.get("text") or "")[:160], "status": cell.get("status"), "engine": result.get("engine"),
                               "kind": cell.get("kind")}
    return out


@bp.get("/api/projects/<pid>/runs")
def api_project_runs(pid):
    project = projects.project_path(pid)
    runs = list_runs(project, limit=int(request.args.get("limit") or 60))
    known = _cells_by_run(pid)
    for run in runs:
        cell = known.get(run["id"])
        if cell:
            run["cell"] = cell
            if not run.get("goal"):
                run["goal"] = cell["text"]
            if run.get("status") == "unknown":
                run["status"] = {"done": "succeeded", "failed": "failed", "stopped": "cancelled", "partial": "partial"}.get(cell["status"], "unknown")
            run["engine"] = cell.get("engine") or ("code" if cell.get("kind") == "code" else "")
        elif run.get("status") == "unknown":
            run["engine"] = "quick"
            run["status"] = "script"
    return jsonify({"runs": runs})


@bp.get("/api/projects/<pid>/runs/<rid>/report")
def api_project_run_report(pid, rid):
    project = projects.project_path(pid)
    try:
        run_dir = RunDir.open(project, rid)
    except FileNotFoundError:
        return jsonify({"error": "no such run"}), 404

    def read(path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read()
        except OSError:
            return ""

    transcript = Transcript.read(run_dir.transcript_path) if os.path.isfile(run_dir.transcript_path) else []
    return jsonify({"id": rid, "report": read(run_dir.report_md), "plan": read(run_dir.plan_md),
                    "state": run_dir.read_json("state.json"), "transcript": transcript[-400:],
                    "path": run_dir.path})
