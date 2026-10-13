# Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""Projects, Patchbooks, cells and the files of a project."""

from __future__ import annotations

import os

from flask import Blueprint, Response, current_app, jsonify, request, send_from_directory

from . import config, projects

bp = Blueprint("projects", __name__)


def _body() -> dict:
    return request.get_json(force=True, silent=True) or {}


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
@bp.get("/api/projects")
def api_projects_list():
    cfg = config.load()
    return jsonify({"projects": projects.list_projects(), "projectsDir": config.projects_dir(cfg), "lastProjectId": cfg.get("lastProjectId", "")})


@bp.post("/api/projects")
def api_projects_create():
    body = _body()
    if body.get("sample"):
        return jsonify(projects.create_sample_project())
    return jsonify(projects.create_project(body.get("name", ""), body.get("description", "")))


@bp.post("/api/projects/import")
def api_projects_import():
    body = _body()
    return jsonify(projects.import_folder(body.get("path", ""), body.get("name", "")))


@bp.get("/api/projects/<pid>")
def api_project_get(pid):
    return jsonify(projects.get_project(pid))


@bp.post("/api/projects/<pid>/open")
def api_project_open(pid):
    return jsonify(projects.touch_opened(pid))


@bp.patch("/api/projects/<pid>")
def api_project_update(pid):
    return jsonify(projects.update_project(pid, _body()))


@bp.delete("/api/projects/<pid>")
def api_project_delete(pid):
    state = current_app.extensions["patchbook"]
    if state["runs"].active_for_project(pid):
        return jsonify({"error": "A patch is still running in this project. Stop it first."}), 409
    return jsonify(projects.delete_project(pid))


@bp.post("/api/projects/<pid>/duplicate")
def api_project_duplicate(pid):
    return jsonify(projects.duplicate_project(pid, _body().get("name", "")))


# ---------------------------------------------------------------------------
# Patchbooks
# ---------------------------------------------------------------------------
@bp.get("/api/projects/<pid>/patchbooks")
def api_patchbooks_list(pid):
    return jsonify({"patchbooks": projects.list_patchbooks(pid)})


@bp.post("/api/projects/<pid>/patchbooks")
def api_patchbooks_create(pid):
    return jsonify(projects.create_patchbook(pid, _body().get("name", "")))


@bp.get("/api/projects/<pid>/patchbooks/<nid>")
def api_patchbook_get(pid, nid):
    return jsonify(projects.get_patchbook(pid, nid))


@bp.put("/api/projects/<pid>/patchbooks/<nid>")
def api_patchbook_put(pid, nid):
    """Save the whole Patchbook. Cells that are running on the server keep the
    server's copy, so an autosave sent while a run finishes cannot erase a result."""
    body = _body()
    state = current_app.extensions["patchbook"]
    try:
        stored = projects.get_patchbook(pid, nid)
    except projects.NotFound:
        stored = None
    if stored and isinstance(body.get("cells"), list):
        active = state["runs"].active_for_project(pid)
        stored_cells = {c["id"]: c for c in stored["cells"]}
        for index, cell in enumerate(body["cells"]):
            if not isinstance(cell, dict):
                continue
            old = stored_cells.get(cell.get("id"))
            if old is None:
                continue
            running_here = active and active["cellId"] == cell.get("id")
            client_thinks_running = cell.get("status") in ("running", "queued")
            server_finished_newer = (old.get("result") and old.get("runId") and old.get("runId") == cell.get("runId")
                                     and client_thinks_running)
            if running_here or server_finished_newer:
                keep = dict(old)
                keep["text"] = cell.get("text", old.get("text"))
                keep["options"] = {**old.get("options", {}), **(cell.get("options") or {})}
                body["cells"][index] = keep
    return jsonify(projects.save_patchbook(pid, nid, body))


@bp.patch("/api/projects/<pid>/patchbooks/<nid>")
def api_patchbook_patch(pid, nid):
    body = _body()
    book = projects.get_patchbook(pid, nid)
    if "name" in body and str(body["name"]).strip():
        book["name"] = str(body["name"]).strip()
    if isinstance(body.get("settings"), dict):
        book["settings"].update({k: v for k, v in body["settings"].items() if k in ("engine", "language", "effort")})
    return jsonify(projects.save_patchbook(pid, nid, book))


@bp.delete("/api/projects/<pid>/patchbooks/<nid>")
def api_patchbook_delete(pid, nid):
    state = current_app.extensions["patchbook"]
    active = state["runs"].active_for_project(pid)
    if active and active["patchbookId"] == nid:
        return jsonify({"error": "A patch is still running in this Patchbook. Stop it first."}), 409
    return jsonify(projects.delete_patchbook(pid, nid))


@bp.post("/api/projects/<pid>/patchbooks/<nid>/duplicate")
def api_patchbook_duplicate(pid, nid):
    return jsonify(projects.duplicate_patchbook(pid, nid, _body().get("name", "")))


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
@bp.get("/api/projects/<pid>/files")
def api_files(pid):
    return jsonify({"files": projects.list_files(pid), "root": projects.project_path(pid)})


@bp.get("/api/projects/<pid>/file")
def api_file(pid):
    return jsonify(projects.read_text(pid, request.args.get("path", "")))


@bp.post("/api/projects/<pid>/file")
def api_file_write(pid):
    body = _body()
    return jsonify(projects.write_text(pid, body.get("path", ""), body.get("text", "")))


@bp.get("/projects/<pid>/raw/<path:rel>")
def raw_file(pid, rel):
    root, full = projects.safe_path(pid, rel)
    if os.path.isdir(full):
        return jsonify({"error": "that is a folder"}), 400
    response = send_from_directory(root, os.path.relpath(full, root), conditional=True)
    if request.args.get("download") == "1":
        response.headers["Content-Disposition"] = f'attachment; filename="{os.path.basename(full)}"'
    return response


@bp.post("/api/projects/<pid>/upload")
def api_upload(pid):
    folder = request.form.get("dir", "data")
    saved = []
    for item in request.files.getlist("files"):
        if item and item.filename:
            saved.append(projects.save_upload(pid, folder, item.filename, item.stream))
    return jsonify({"saved": saved})


@bp.delete("/api/projects/<pid>/file")
def api_file_delete(pid):
    return jsonify(projects.delete_path(pid, request.args.get("path", "")))


@bp.post("/api/projects/<pid>/mkdir")
def api_mkdir(pid):
    return jsonify(projects.make_dir(pid, _body().get("path", "")))


@bp.post("/api/projects/<pid>/files/op")
def api_files_op(pid):
    """Bulk operations from the Files panel: delete, duplicate, copy, move, rename, create."""
    body = _body()
    op = str(body.get("op") or "")
    paths = [str(p) for p in (body.get("paths") or []) if p]
    if op == "delete":
        return jsonify(projects.delete_paths(pid, paths))
    if op == "duplicate":
        return jsonify(projects.duplicate_paths(pid, paths))
    if op in ("copy", "move"):
        return jsonify(projects.copy_or_move_paths(pid, paths, str(body.get("target") or ""), move=(op == "move")))
    if op == "rename":
        return jsonify(projects.rename_path(pid, paths[0] if paths else body.get("path", ""), body.get("name", "")))
    if op == "create":
        return jsonify(projects.create_text_file(pid, str(body.get("target") or ""), body.get("name", ""), body.get("text", "")))
    return jsonify({"error": f"unknown operation: {op}"}), 400


@bp.get("/api/projects/<pid>/zip")
def api_zip(pid):
    paths = request.args.getlist("paths")
    if not paths:
        return jsonify({"error": "nothing selected"}), 400
    buffer, count = projects.zip_paths(pid, paths)
    name = (os.path.basename(paths[0]) if len(paths) == 1 else projects.get_project(pid)["name"]) or "files"
    return Response(buffer.getvalue(), mimetype="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{projects.slugify(name, "files")}.zip"', "X-File-Count": str(count)})


def _open_in_os(target: str, reveal: bool = False) -> None:
    import subprocess
    import sys
    if sys.platform.startswith("win"):
        if reveal:
            subprocess.Popen(["explorer", "/select,", target])
        else:
            os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", target] if reveal else ["open", target])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(target) if reveal else target])


@bp.post("/api/projects/<pid>/open-with")
def api_open_with(pid):
    """Open a file with the program this computer uses for it, or show it in the file manager."""
    body = _body()
    _root, full = projects.safe_path(pid, body.get("path", ""))
    try:
        _open_in_os(full, reveal=bool(body.get("reveal")))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Could not open it: {exc}"}), 500
    return jsonify({"ok": True, "path": full})
