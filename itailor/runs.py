# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
Where a run lives on disk (design §2.8):

    <project>/.itailor/runs/<run-id>/
        plan.md · plan.json · state.json · transcript.jsonl
        steps/<n>/ (scripts, outputs) · artifacts/ · report.md · report.json · cache/
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid

RUNS_DIRNAME = os.path.join(".itailor", "runs")


def _slug(text: str, limit: int = 32) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return cleaned[:limit].rstrip("-") or "run"


class RunDir:
    def __init__(self, project: str, run_id: str) -> None:
        self.project = os.path.abspath(project)
        self.id = run_id
        self.path = os.path.join(self.project, RUNS_DIRNAME, run_id)
        self.steps_dir = os.path.join(self.path, "steps")
        self.artifacts_dir = os.path.join(self.path, "artifacts")
        self.cache_dir = os.path.join(self.path, "cache")
        for folder in (self.path, self.steps_dir, self.artifacts_dir, self.cache_dir):
            os.makedirs(folder, exist_ok=True)

    @classmethod
    def create(cls, project: str, goal: str = "") -> "RunDir":
        run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(goal, 24)}-{uuid.uuid4().hex[:4]}"
        return cls(project, run_id)

    @classmethod
    def open(cls, project: str, run_id: str) -> "RunDir":
        path = os.path.join(os.path.abspath(project), RUNS_DIRNAME, run_id)
        if not os.path.isdir(path):
            raise FileNotFoundError(f"no run {run_id} under {project}")
        return cls(project, run_id)

    def file(self, name: str) -> str:
        return os.path.join(self.path, name)

    @property
    def plan_md(self) -> str:
        return self.file("plan.md")

    @property
    def plan_json(self) -> str:
        return self.file("plan.json")

    @property
    def state_json(self) -> str:
        return self.file("state.json")

    @property
    def transcript_path(self) -> str:
        return self.file("transcript.jsonl")

    @property
    def report_md(self) -> str:
        return self.file("report.md")

    @property
    def report_json(self) -> str:
        return self.file("report.json")

    def write_json(self, name: str, data) -> None:
        with open(self.file(name), "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False, default=str)

    def read_json(self, name: str):
        try:
            with open(self.file(name), "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:  # noqa: BLE001
            return None

    def write_text(self, name: str, text: str) -> None:
        with open(self.file(name), "w", encoding="utf-8") as handle:
            handle.write(text)

    def collect_artifact(self, path: str, step_id: str = "") -> dict | None:
        """Copy a produced file into artifacts/ (hard-link when possible) and describe it."""
        if not path or not os.path.isfile(path):
            return None
        name = os.path.basename(path)
        target = os.path.join(self.artifacts_dir, name)
        if os.path.abspath(path) != os.path.abspath(target):
            try:
                if os.path.exists(target):
                    os.remove(target)
                try:
                    os.link(path, target)
                except OSError:
                    shutil.copy2(path, target)
            except OSError:
                target = path
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        rel = os.path.relpath(path, self.project).replace(os.sep, "/") if path.startswith(self.project) else path
        return {"name": name, "path": rel, "size": size, "step": step_id,
                "type": os.path.splitext(name)[1].lstrip(".").lower() or "file"}


def list_runs(project: str, limit: int = 50) -> list[dict]:
    root = os.path.join(os.path.abspath(project), RUNS_DIRNAME)
    if not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root), reverse=True)[:limit]:
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        state = {}
        try:
            with open(os.path.join(path, "state.json"), "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except Exception:  # noqa: BLE001
            pass
        out.append({"id": name, "goal": state.get("goal", ""), "status": state.get("status", "unknown"),
                    "started": state.get("started", ""), "finished": state.get("finished", ""),
                    "hasReport": os.path.isfile(os.path.join(path, "report.md"))})
    return out
