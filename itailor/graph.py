# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
The project knowledge graph: what iTailor knows about a project, as a graph
a human can read - ``<project>/.itailor/graph.yaml``.

DAYA Studio's knowledge graph described one program (imports, functions,
variables, files). This one describes a project across runs: the
environment it was last seen in, the runs and their plans, each step with
its status and check, the files produced and which step produced them, the
permission decisions made and for which tool, the lessons recorded, and
the open items. The agent reads a compact summary of it into every prompt
(so a second run knows what the first left behind) and writes to it as it
goes; the file is also the human's view of "what has this project been
through, and what did I decide".

Two rules keep it honest: it is *derived* - everything in it also exists in
run state and transcripts, so it can be rebuilt (``rebuild``) and is never
the oracle for anything; and it is *bounded* - only the last ``keep_runs``
runs keep their steps and decisions, older runs shrink to one node.
"""

from __future__ import annotations

import os
import time
from typing import Any

from . import yamllite
from .runs import RunDir, list_runs

SCHEMA = "1.0"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class ProjectGraph:
    def __init__(self, path: str, *, keep_runs: int = 20) -> None:
        self.path = path
        self.keep_runs = keep_runs
        self.data: dict = {"schemaVersion": SCHEMA, "project": os.path.dirname(os.path.dirname(path)),
                           "updated": _now(), "environment": {}, "state": {"openItems": []},
                           "nodes": {}, "edges": []}
        self._load()

    # -- persistence ---------------------------------------------------------
    def _load(self) -> None:
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                loaded = yamllite.load(handle.read())
            if isinstance(loaded, dict) and isinstance(loaded.get("nodes"), dict):
                self.data.update(loaded)
                self.data.setdefault("edges", [])
                self.data.setdefault("state", {"openItems": []})
                self.data.setdefault("environment", {})
        except Exception:  # noqa: BLE001 - a damaged graph is rebuilt, not fatal
            pass

    def save(self) -> None:
        self.data["updated"] = _now()
        self._prune()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("# iTailor project knowledge graph - derived from runs; safe to edit or delete.\n")
            handle.write(yamllite.dump(self.data))

    # -- graph primitives ----------------------------------------------------
    @property
    def nodes(self) -> dict:
        return self.data["nodes"]

    @property
    def edges(self) -> list:
        return self.data["edges"]

    def node(self, node_id: str, kind: str, **attrs: Any) -> dict:
        entry = self.nodes.get(node_id)
        if entry is None:
            entry = {"kind": kind}
            self.nodes[node_id] = entry
        entry["kind"] = kind
        for key, value in attrs.items():
            if value is not None:
                entry[key] = value
        entry["seen"] = _now()
        return entry

    def edge(self, src: str, rel: str, dst: str) -> None:
        record = {"src": src, "rel": rel, "dst": dst}
        if record not in self.edges:
            self.edges.append(record)

    def neighbours(self, node_id: str, rel: str | None = None, direction: str = "out") -> list[str]:
        out = []
        for e in self.edges:
            if rel and e["rel"] != rel:
                continue
            if direction in ("out", "both") and e["src"] == node_id:
                out.append(e["dst"])
            if direction in ("in", "both") and e["dst"] == node_id:
                out.append(e["src"])
        return out

    def nodes_of(self, kind: str) -> dict:
        return {k: v for k, v in self.nodes.items() if v.get("kind") == kind}

    def find(self, text: str, limit: int = 20) -> list[tuple[str, dict]]:
        needle = str(text or "").lower()
        hits = [(k, v) for k, v in self.nodes.items() if needle in k.lower() or needle in str(v).lower()]
        return hits[:limit]

    # -- recording -----------------------------------------------------------
    def record_environment(self, manifest: dict) -> None:
        if not manifest:
            return
        o, h = manifest.get("os", {}), manifest.get("hardware", {})
        self.data["environment"] = {
            "os": f"{o.get('system', '')} {o.get('release', '')}".strip(), "arch": o.get("arch", ""),
            "cores": h.get("cores"), "ramTotalGb": h.get("ramTotalGb"),
            "gpus": [g.get("name") for g in h.get("gpus") or []],
            "interpreters": {k: v.get("version", "") for k, v in (manifest.get("interpreters") or {}).items()},
            "packageManagers": sorted((manifest.get("packageManagers") or {}).keys()),
            "appsCount": len(manifest.get("apps") or []),
            "pythonPackages": sorted(((manifest.get("pythonPackages") or {}).get("known") or {}).keys()),
            "seen": manifest.get("generatedAt") or _now(),
        }
        for name in (manifest.get("interpreters") or {}):
            self.node(f"tool:{name}", "tool", label=name, version=(manifest["interpreters"][name] or {}).get("version", ""))

    def record_run_start(self, run_id: str, goal: str, mode: str = "") -> None:
        self.node(f"run:{run_id}", "run", goal=goal[:300], status="running", started=_now(), mode=mode)
        self.data["state"]["currentRun"] = run_id

    def record_plan(self, run_id: str, plan: dict) -> None:
        run_node = f"run:{run_id}"
        self.node(run_node, "run", restatement=(plan.get("restatement") or "")[:300], revision=plan.get("revision", 0))
        for step in plan.get("steps") or []:
            sid = f"step:{run_id}:{step.get('id')}"
            self.node(sid, "step", title=step.get("title", ""), status=step.get("status", "pending"),
                      kind_of_step=step.get("kind", ""), check=step.get("check") or {}, run=run_id,
                      outputs=list(step.get("outputs") or []), inputs=list(step.get("inputs") or []))
            self.edge(sid, "in_run", run_node)
            for dep in step.get("depends_on") or []:
                self.edge(sid, "depends_on", f"step:{run_id}:{dep}")
            for item in step.get("inputs") or []:
                self.edge(sid, "reads", f"file:{item}")
                self.node(f"file:{item}", "file", label=item)

    def record_step(self, run_id: str, step: dict, artifacts: list | None = None) -> None:
        sid = f"step:{run_id}:{step.get('id')}"
        checks = step.get("check_results") or []
        self.node(sid, "step", title=step.get("title", ""), status=step.get("status", ""), attempts=step.get("attempts", 0),
                  summary=(step.get("summary") or "")[:300], run=run_id,
                  verified=bool(checks) and all(c.get("passed") for c in checks))
        for art in artifacts or []:
            path = art.get("path") if isinstance(art, dict) else str(art)
            fid = f"file:{path}"
            self.node(fid, "file", label=path, size=art.get("size") if isinstance(art, dict) else None,
                      producedBy=sid, run=run_id)
            self.edge(sid, "produced", fid)

    def record_decision(self, run_id: str, decision: dict) -> None:
        index = len(self.nodes_of("decision")) + 1
        did = f"decision:{run_id}:{index}"
        tool = decision.get("tool") or decision.get("gate") or "?"
        self.node(did, "decision", tool=tool, command=(decision.get("command") or "")[:160],
                  decision=decision.get("decision", ""), source=decision.get("source", ""),
                  reason=(decision.get("reason") or "")[:160], run=run_id)
        self.edge(did, "in_run", f"run:{run_id}")
        self.edge(did, "about_tool", f"tool:{tool}")
        self.node(f"tool:{tool}", "tool", label=tool)

    def record_lesson(self, lesson: dict, run_id: str = "") -> None:
        lid = f"lesson:{lesson.get('id')}"
        self.node(lid, "lesson", kind_of_lesson=lesson.get("kind", ""), decision=lesson.get("decision", ""),
                  fix=(lesson.get("fix") or "")[:200], situation=lesson.get("situation") or {})
        if run_id:
            self.edge(lid, "learned_in", f"run:{run_id}")

    def record_run_end(self, run_id: str, status: str, summary: str = "", open_items: list | None = None) -> None:
        self.node(f"run:{run_id}", "run", status=status, finished=_now(), summary=(summary or "")[:500])
        self.data["state"]["lastRun"] = run_id
        self.data["state"]["lastStatus"] = status
        self.data["state"]["openItems"] = list(open_items or [])[:20]
        if self.data["state"].get("currentRun") == run_id:
            self.data["state"]["currentRun"] = ""

    # -- bounds and rebuild --------------------------------------------------
    def _prune(self) -> None:
        runs = sorted(self.nodes_of("run").items(), key=lambda kv: kv[1].get("started") or "", reverse=True)
        stale = {k.split(":", 1)[1] for k, _ in runs[self.keep_runs:]}
        if not stale:
            return
        for node_id in list(self.nodes):
            kind = self.nodes[node_id].get("kind")
            if kind in ("step", "decision") and self.nodes[node_id].get("run") in stale:
                del self.nodes[node_id]
        self.data["edges"] = [e for e in self.edges if e["src"] in self.nodes and e["dst"] in self.nodes]

    def rebuild(self, project: str) -> None:
        """Rebuild from the run folders (state.json). The graph is derived data."""
        self.data["nodes"], self.data["edges"] = {}, []
        for info in reversed(list_runs(project, limit=self.keep_runs)):
            try:
                run_dir = RunDir.open(project, info["id"])
            except FileNotFoundError:
                continue
            state = run_dir.read_json("state.json") or {}
            if not state:
                continue
            self.record_run_start(info["id"], state.get("goal", ""), state.get("mode", ""))
            if state.get("plan"):
                self.record_plan(info["id"], state["plan"])
            by_step: dict = {}
            for art in state.get("artifacts") or []:
                by_step.setdefault(art.get("step") or "", []).append(art)
            for step in state.get("steps") or []:
                self.record_step(info["id"], step, by_step.get(step.get("id")))
            for decision in state.get("decisions") or []:
                self.record_decision(info["id"], decision)
            self.record_run_end(info["id"], state.get("status", ""), state.get("summary", ""), state.get("openItems"))

    # -- the prompt view -----------------------------------------------------
    def summary(self, max_runs: int = 3, max_files: int = 15, max_decisions: int = 8) -> str:
        runs = sorted(self.nodes_of("run").items(), key=lambda kv: kv[1].get("started") or "", reverse=True)
        if not runs and not self.data.get("environment"):
            return ""
        lines = ["PROJECT STATE (from .itailor/graph.yaml - what earlier runs left behind):"]
        for run_id, run in runs[:max_runs]:
            lines.append(f"- run {run_id.split(':', 1)[1]} [{run.get('status')}]: {run.get('goal', '')[:120]}"
                         + (f" -> {run.get('summary', '')[:160]}" if run.get("summary") else ""))
        files = sorted(self.nodes_of("file").items(), key=lambda kv: kv[1].get("seen") or "", reverse=True)
        produced = [(k, v) for k, v in files if v.get("producedBy")]
        if produced:
            lines.append("- files produced earlier: " + ", ".join(
                f"{v.get('label')} (by {v['producedBy'].split(':')[-1]})" for _k, v in produced[:max_files]))
        decisions = [v for _k, v in self.nodes_of("decision").items() if v.get("source") in ("user", "user or timeout", "standing grant")]
        if decisions:
            lines.append("- your earlier answers to permission questions: " + "; ".join(
                f"{d.get('tool')} '{d.get('command', '')[:40]}' -> {d.get('decision')}" for d in decisions[-max_decisions:]))
        open_items = self.data.get("state", {}).get("openItems") or []
        if open_items:
            lines.append("- open items from the last run: " + "; ".join(str(i)[:120] for i in open_items[:5]))
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return self.data


def graph_path(project: str) -> str:
    return os.path.join(os.path.abspath(project), ".itailor", "graph.yaml")
