# Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
Running a cell with iTailor and following it live.

One run = one cell. The run manager starts ``itailor.Agent`` instances bound
to the project folder in a worker thread, relays every event they emit to the
browser (server-sent events, replayed from the start for a page that
reconnects), holds permission and consultation questions until the browser
answers them, and when the run ends writes the result into the cell on disk.

A run is a sequence of **approaches** chosen by the effort level
(``strategy.py``): a script repaired until it works; a different approach that
knows what failed; a step-by-step plan with verified steps; a different plan;
and finally a question to the human. Each approach is one iTailor engine call
with its own, deliberate stopping rule; Patchbook decides what comes next.

Engines (what one approach asks iTailor to do):
    quick      the one-shot script engine: write one script, run it, repair it, print the answer
    thorough   the goal loop: understand, plan, execute step by step, verify, report
    ask        a single conversational turn with tools (an answer in prose; may read or run things)
    code       run the code in a code cell as it is (no model involved)
"""

from __future__ import annotations

import fnmatch
import glob
import json
import os
import queue
import re
import threading
import time
import uuid

import itailor
from itailor import checks as checks_module, languages as languages_module
from itailor.events import CancelToken, RunCancelled
from itailor.oversight import ConsultRequest, QueueOversight
from itailor.runs import RunDir
from itailor.tools import runcode

from . import activity, projects, recommend, shared_store, strategy
from .demo import demo_client

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"}
TABLE_EXT = {".csv", ".tsv", ".xlsx", ".xls", ".parquet", ".feather"}
TEXT_EXT = {".md", ".txt", ".json", ".yaml", ".yml", ".html", ".htm", ".log", ".py", ".r", ".js", ".sql", ".xml", ".tex"}
RECORD_TYPES = {"run_start", "think", "plan", "step_start", "step_done", "observe", "tool_call", "tool_result",
                "permission_request", "consult_request", "consult_answer", "decision", "lesson", "final", "error", "run_end",
                "patchbook_strategy", "patchbook_attempt", "patchbook_auto"}
ENGINES = ("quick", "thorough", "ask", "code")
STATUS_WORD = {"done": "done", "failed": "did not finish", "partial": "partly done", "stopped": "stopped"}
OWN_FILES = {"patchbook-project.json", "ITAILOR.md", ".gitignore", "shared/state.json"}
OWN_DIRS = ("patchbooks/", ".itailor/", "__pycache__/")


class Busy(Exception):
    pass


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def classify(path: str) -> str:
    ext = os.path.splitext(str(path or ""))[1].lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in TABLE_EXT:
        return "table"
    if ext in TEXT_EXT:
        return "text"
    return "other"


def parse_checks(specs) -> list:
    """``file:PATH``, ``stdout:REGEX``, ``csv:PATH@MINROWS``, ``json:PATH``, ``cmd:COMMAND``."""
    out = []
    for spec in specs or []:
        spec = str(spec).strip()
        if not spec:
            continue
        kind, _, arg = spec.partition(":")
        kind = kind.strip().lower()
        arg = arg.strip()
        if kind in ("file", "file_exists") and arg:
            out.append(checks_module.file_exists(arg))
        elif kind == "stdout" and arg:
            out.append(checks_module.stdout_matches(arg))
        elif kind == "csv" and arg:
            path, _, rows = arg.partition("@")
            out.append(checks_module.csv_rows(path, int(rows or 1)))
        elif kind == "json" and arg:
            out.append(checks_module.json_valid(arg))
        elif kind == "cmd" and arg:
            out.append(checks_module.command_exit_zero(arg))
    return out


def _rel(project: str, path) -> str:
    text = str(path or "")
    if not text:
        return ""
    try:
        if os.path.isabs(text):
            rel = os.path.relpath(text, project)
            if not rel.startswith(".."):
                return rel.replace(os.sep, "/")
            return text
    except ValueError:
        return text
    return text.replace(os.sep, "/")


def _files(project: str, items) -> list[dict]:
    """Produced or changed files, without Patchbook's and iTailor's own bookkeeping."""
    out: list[dict] = []
    seen: set[str] = set()
    for item in items or []:
        path = item.get("path") if isinstance(item, dict) else item
        rel = _rel(project, path)
        if not rel or rel in seen or rel in OWN_FILES or rel.startswith(OWN_DIRS) or "/__pycache__/" in rel:
            continue
        seen.add(rel)
        full = rel if os.path.isabs(rel) else os.path.join(project, rel)
        size = os.path.getsize(full) if os.path.isfile(full) else None
        out.append({"path": rel, "name": os.path.basename(rel), "kind": classify(rel), "size": size,
                    "step": item.get("step", "") if isinstance(item, dict) else ""})
    return out


# ---------------------------------------------------------------------------
# What the model is told besides the task
# ---------------------------------------------------------------------------
def build_context(book: dict, cell_id: str, *, keep_recent: int = 12) -> tuple[str, list]:
    """What iTailor is told about the earlier cells of the Patchbook, plus the
    (task, code) history the script engine can continue from."""
    prior: list[dict] = []
    for cell in book.get("cells") or []:
        if cell.get("id") == cell_id:
            break
        prior.append(cell)
    lines: list[str] = []
    history: list[dict] = []
    recent_from = max(0, len(prior) - keep_recent)
    for index, cell in enumerate(prior):
        options = cell.get("options") or {}
        if options.get("excluded") or (index < recent_from and not options.get("pinned")):
            continue
        text = str(cell.get("text") or "").strip()
        result = cell.get("result") if isinstance(cell.get("result"), dict) else {}
        number = index + 1
        if cell.get("kind") == "note":
            if text:
                lines.append(f"Note {number}: {text[:400]}")
            continue
        if not text and not result:
            continue
        entry = f"{'Code cell' if cell.get('kind') == 'code' else 'Patch'} {number}: {text[:500]}"
        if result:
            entry += f"\n  status: {cell.get('status')}"
            files = [f.get("path") for f in (result.get("files") or []) if isinstance(f, dict) and f.get("path")]
            if files:
                entry += "\n  produced: " + ", ".join(files[:12])
            output = str(result.get("summary") or result.get("stdout") or "").strip()
            if output:
                entry += "\n  result: " + " ".join(output[:400].split())
            if result.get("code") and cell.get("kind") == "patch":
                history.append({"task": text, "code": str(result["code"])})
        lines.append(entry)
    if not lines:
        return "", []
    header = ("This request is one cell of a Patchbook: a notebook of plain-language patches that run in order in this "
              "project folder. The earlier cells and what they produced are listed below. Files they produced are in the "
              "project folder and can be reused; do not redo earlier work unless this request asks for it.")
    return header + "\n\n" + "\n".join(lines), history[-6:]


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1048576:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1048576:.1f} MB"


def project_listing(project: str, *, max_entries: int = 200, max_depth: int = 4, max_chars: int = 2500) -> str:
    """What is in the project folder, listed deterministically before the model is asked anything.

    The script engine writes one script from the prompt alone, so it can only open files it has
    been shown. This is the equivalent of an analyst running ``ls -R`` before writing a line."""
    entries: list[str] = []
    total = 0
    for dirpath, dirs, files in os.walk(project):
        rel_dir = os.path.relpath(dirpath, project).replace(os.sep, "/")
        depth = 0 if rel_dir == "." else rel_dir.count("/") + 1
        dirs[:] = sorted(d for d in dirs if d not in projects.HIDDEN_DIRS and not d.startswith(".")) if depth < max_depth else []
        for name in sorted(files):
            if name.startswith(".") or name in projects.HIDDEN_FILES or name in OWN_FILES or name.endswith(".tmp"):
                continue
            total += 1
            if len(entries) >= max_entries:
                continue
            rel = f"{rel_dir}/{name}" if rel_dir != "." else name
            try:
                size = os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                size = 0
            entries.append(f"{rel} ({_fmt_size(size)})")
    if not entries:
        return "FILES IN THE PROJECT FOLDER: none yet (apart from Patchbook's own files). Files you create go into this folder."
    text = "\n".join(entries)
    if total > len(entries):
        text += f"\n... and {total - len(entries)} more files (search the folder for the rest)"
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...(listing cut; search the folder for the rest)"
    return "FILES IN THE PROJECT FOLDER (paths relative to the working directory, which is the project folder):\n" + text


FILE_GUIDANCE = (
    "Refer to files by the relative paths listed above; subfolders such as data/ count. If the task mentions a file, a "
    "document or a kind of file that is not in the listing where you expect it, search the whole project folder "
    "(for example with os.walk) before concluding it does not exist, and say in the printed summary what you searched "
    "and what you found. You may read, create and change files in the project folder; save what you produce there with clear names."
)


def compose_context(agent, project: str, patchbook_context: str, *, engine: str, evidence: str = "", hints: list | None = None) -> str:
    """Everything the model should know besides the task: the project's ITAILOR.md (the script engine does not
    read it by itself), the file listing, the shared store, the earlier cells, what failed before, the user's hints,
    and how to look for files."""
    parts: list[str] = []
    if engine == "quick":
        texts = [c.get("text", "") for c in (agent.context_files or []) if c.get("scope") in ("project", "parent")]
        context_text = "\n\n".join(t for t in texts if t).strip()
        if context_text:
            parts.append("PROJECT NOTES (ITAILOR.md):\n" + context_text[:3000])
    parts.append(project_listing(project, max_chars=2500 if engine == "quick" else 1500))
    parts.append(shared_store.prompt_block(project, max_chars=1800 if engine == "quick" else 1000))
    if patchbook_context:
        parts.append(patchbook_context)
    if evidence:
        parts.append(evidence)
    hint_text = strategy.hints_block(hints or [])
    if hint_text:
        parts.append(hint_text)
    parts.append(FILE_GUIDANCE)
    if engine == "quick":
        parts.append(strategy.QUICK_PROTOCOL)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Acceptance checks for one-script runs: the model proposes what must be true, Patchbook verifies it on disk
# ---------------------------------------------------------------------------
DERIVE_SYSTEM = (
    "You decide what must be true after a task is done, so that it can be verified without trusting the script that did it. "
    "Reply with JSON only, no prose: {\"files\": [...]} where files is a list of glob patterns, relative to the project folder, "
    "of files the task must have created or updated (for example \"*.pdf\", \"results/*.csv\", \"report.md\"). Prefer a pattern "
    "over an exact name unless the task names the file. Use an empty list when the task only prints, answers or inspects."
)


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else ""


def fresh_glob_check(pattern: str, since: float):
    """Passes when a non-empty file matching ``pattern`` was created or updated after ``since``.
    A pattern without a slash matches that file name anywhere in the project."""
    name = f"produced {pattern}"

    def fn(ctx):
        root = ctx.project
        matches: list[str] = []
        if "/" in pattern or "\\" in pattern:
            candidates = glob.glob(os.path.join(root, pattern.replace("\\", "/")), recursive=True)
        else:
            candidates = []
            for dirpath, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d not in projects.HIDDEN_DIRS and not d.startswith(".")]
                candidates.extend(os.path.join(dirpath, f) for f in files if fnmatch.fnmatch(f, pattern))
        for path in candidates:
            rel = _rel(root, path)
            if rel in OWN_FILES or rel.startswith(OWN_DIRS) or not os.path.isfile(path):
                continue
            try:
                if os.path.getsize(path) > 0 and os.path.getmtime(path) >= since - 1:
                    matches.append(rel)
            except OSError:
                continue
        if matches:
            return checks_module.CheckResult(name, True, "found " + ", ".join(sorted(matches)[:5]))
        return checks_module.CheckResult(name, False, f"no file matching {pattern} was created or updated by this run")
    return checks_module.custom(fn, name=name)


def derive_checks(client, task: str, listing: str, since: float, emit=None) -> list:
    """Ask the model what files the task must produce; turn the answer into checks Patchbook verifies itself."""
    if client is None:
        return []
    try:
        reply = client.complete([{"role": "system", "content": DERIVE_SYSTEM},
                                 {"role": "user", "content": f"Task: {task}\n\n{listing[:1500]}"}], max_tokens=300)
        text = reply.text if hasattr(reply, "text") else str(reply)
        data = json.loads(_extract_json(str(text or "")))
    except Exception:  # noqa: BLE001 - no checks is acceptable; a wrong check is not
        return []
    out = []
    for pattern in (data.get("files") if isinstance(data, dict) else None) or []:
        if isinstance(pattern, str) and pattern.strip() and len(out) < 5 and ".." not in pattern:
            out.append(fresh_glob_check(pattern.strip(), since))
    if out and emit:
        emit("observe", "To count as done, this run must produce: " + ", ".join(c.name.replace("produced ", "") for c in out))
    return out


# ---------------------------------------------------------------------------
# Results of one approach
# ---------------------------------------------------------------------------
def _result_quick(r, project: str) -> dict:
    error = r.error
    if not r.success:
        # The library says why it stopped; the last line of the error output says what actually broke.
        lines = [line for line in str(r.stderr or "").strip().splitlines() if line.strip()]
        if lines:
            error = (f"{error} " if error else "") + f"(last error: {lines[-1].strip()[:300]})"
    failures = [dict(a.get("failure") or {}) for a in (r.attempts or []) if isinstance(a, dict) and a.get("failure")]
    return {"engine": "quick", "ok": bool(r.success), "summary": str(r.stdout or "").strip(), "code": r.code,
            "language": r.language, "stdout": r.stdout, "stderr": r.stderr, "files": _files(project, r.files),
            "error": error, "iterations": r.iterations, "checks": list(r.checks or []), "notes": list(r.notes or []),
            "failures": failures, "runDir": _rel(project, r.run_dir), "stopReason": r.stop_reason}


def _result_thorough(r, project: str) -> dict:
    steps = []
    for step in (r.plan or {}).get("steps") or []:
        if isinstance(step, dict):
            steps.append({"id": step.get("id"), "title": step.get("title"), "status": step.get("status"),
                          "summary": step.get("summary", ""), "attempts": step.get("attempts", 0)})
    return {"engine": "thorough", "ok": bool(r.ok), "status": r.status, "summary": r.summary, "files": _files(project, r.files),
            "reportPath": _rel(project, r.report_path), "restatement": (r.plan or {}).get("restatement", ""),
            "planSteps": steps, "checks": list(r.checks or []), "usage": dict(r.usage or {}), "error": r.error,
            "runId": r.run_id}


def _result_ask(t, project: str) -> dict:
    return {"engine": "ask", "ok": bool(t.ok), "summary": t.text, "files": _files(project, t.files), "error": t.error,
            "toolSteps": t.steps, "tools": [{"name": x.get("name"), "ok": x.get("ok")} for x in (t.tool_results or [])]}


def _result_code(out: dict, code: str, language: str, project: str) -> dict:
    ok = bool(out.get("success"))
    stderr = str(out.get("stderr") or "")
    error = None if ok else (f"exit code {out.get('exitCode')}" + (": " + stderr.strip()[-600:] if stderr.strip() else ""))
    return {"engine": "code", "ok": ok, "summary": str(out.get("stdout") or "").strip(), "code": code, "language": language,
            "stdout": out.get("stdout", ""), "stderr": stderr, "files": _files(project, out.get("files")), "error": error,
            "exitCode": out.get("exitCode"), "notes": list(out.get("notes") or [])}


class RunManager:
    MAX_LOG = 6000
    KEEP_FINISHED = 80

    def __init__(self) -> None:
        self.runs: dict[str, dict] = {}
        self.lock = threading.Lock()

    # ------------------------------------------------------------------
    def active(self) -> list[dict]:
        return [self.public(e) for e in list(self.runs.values()) if e["status"] in ("starting", "running")]

    def active_for_project(self, project_id: str) -> dict | None:
        for entry in list(self.runs.values()):
            if entry["projectId"] == project_id and entry["status"] in ("starting", "running"):
                return entry
        return None

    def get(self, run_id: str) -> dict | None:
        return self.runs.get(run_id)

    def public(self, entry: dict) -> dict:
        keys = ("id", "projectId", "patchbookId", "cellId", "engine", "effort", "task", "status", "started", "finished", "result",
                "error", "demo", "model", "attempts")
        data = {k: entry.get(k) for k in keys}
        data["pending"] = entry["oversight"].pending() if entry.get("oversight") else []
        return data

    def _prune(self) -> None:
        finished = sorted((e for e in self.runs.values() if e["status"] not in ("starting", "running")),
                          key=lambda e: e.get("finished") or 0)
        for entry in finished[: max(0, len(finished) - self.KEEP_FINISHED)]:
            self.runs.pop(entry["id"], None)

    # ------------------------------------------------------------------
    def start(self, spec: dict) -> dict:
        pid, nid, cid = spec["projectId"], spec["patchbookId"], spec["cellId"]
        project = spec["projectPath"]
        engine = spec.get("engine") if spec.get("engine") in ENGINES else "quick"
        effort = strategy.normalize(spec.get("effort"))
        task = str(spec.get("task") or "").strip()
        with self.lock:
            busy = self.active_for_project(pid)
            if busy:
                raise Busy("Another patch is still running in this project. Wait for it or stop it first.")
            self._prune()
            run_id = uuid.uuid4().hex[:10]
            entry: dict = {"id": run_id, "projectId": pid, "patchbookId": nid, "cellId": cid, "cellIndex": spec.get("cellIndex"),
                           "engine": engine, "effort": effort,
                           "task": task[:300], "status": "starting", "started": time.time(), "finished": None, "log": [],
                           "subscribers": [], "seq": 0, "sublock": threading.Lock(), "steps": [], "result": None, "error": "",
                           "agent": None, "oversight": None, "cancel": CancelToken(), "demo": bool(spec.get("demo")), "model": "",
                           "attempts": []}
            self.runs[run_id] = entry

        def publish(payload: dict) -> None:
            payload.setdefault("ts", time.time())
            with entry["sublock"]:
                entry["seq"] += 1
                payload["n"] = entry["seq"]
                entry["log"].append(payload)
                if len(entry["log"]) > self.MAX_LOG:
                    del entry["log"][: len(entry["log"]) - self.MAX_LOG]
                if payload.get("type") in RECORD_TYPES:
                    entry["steps"].append({"at": payload["ts"], "type": payload["type"], "text": str(payload.get("message") or "")[:300]})
                    if len(entry["steps"]) > 80:
                        del entry["steps"][: len(entry["steps"]) - 80]
                subscribers = list(entry["subscribers"])
            for subscriber in subscribers:
                subscriber.put(payload)

        def close_stream() -> None:
            with entry["sublock"]:
                subscribers = list(entry["subscribers"])
            for subscriber in subscribers:
                subscriber.put(None)

        autonomy = str(spec.get("autonomy") or "ask")

        def on_request(payload: dict) -> None:
            """Every question gets a recommendation; in autonomous mode, clear cases are answered here and now."""
            advice = recommend.recommend(payload)
            payload["recommendation"] = advice          # on the question itself, so the pending list carries it too
            auto = autonomy == "auto" and payload.get("requestType") != "consult" and advice["confident"] and advice["decision"] in ("allow", "deny")
            publish({"type": "oversight", "message": payload.get("summary") or payload.get("question") or "", "auto": auto, **payload})
            if auto:
                publish({"type": "patchbook_auto", "message": ("Allowed automatically: " if advice["decision"] == "allow" else "Refused automatically: ")
                         + str(payload.get("summary") or "") + " (" + advice["reason"] + ")", "decision": advice["decision"],
                         "requestId": payload.get("requestId"), "reason": advice["reason"]})
                oversight.resolve(str(payload.get("requestId") or ""), advice["decision"])

        oversight = QueueOversight(on_request=on_request)
        entry["oversight"] = oversight
        token: CancelToken = entry["cancel"]
        base_overrides: dict = {}
        if spec.get("mode"):
            base_overrides["permissionMode"] = spec["mode"]
        demo = bool(spec.get("demo"))
        context = str(spec.get("context") or "")
        history = list(spec.get("history") or [])
        checks = parse_checks(spec.get("checks") or [])
        language = str(spec.get("language") or "auto")
        code = str(spec.get("code") or "")
        effort_overrides = spec.get("effortOverrides") if isinstance(spec.get("effortOverrides"), dict) else None
        chain = strategy.chain_for(engine, effort, effort_overrides)
        plan = strategy.effort_plan(effort, effort_overrides)
        producer = {"patchbook": nid, "cell": spec.get("cellIndex"), "run": None}

        def make_agent(strat: str):
            overrides = dict(base_overrides)
            overrides.update(strategy.settings_for(strat, effort, effort_overrides))
            agent = itailor.Agent(project, settings=overrides, oversight=oversight,
                                  model=None if demo else (spec.get("model") or None),
                                  client=demo_client(task) if demo else None,
                                  on_event=lambda event: publish(event.to_dict()))
            agent.cancel_token = token          # one stop button for every approach of this run
            entry["agent"] = agent
            return agent

        def finish(cell_status: str, result: dict | None) -> None:
            result = dict(result or {})
            result.setdefault("engine", engine)
            result.setdefault("ok", cell_status == "done")
            result["demo"] = demo
            result["model"] = entry["model"]
            result["effort"] = effort
            result["attempts"] = [{k: a.get(k) for k in ("strategy", "label", "engine", "status", "error", "elapsed", "needsProgram")} for a in entry["attempts"]]
            result["elapsed"] = round(time.time() - entry["started"], 1)
            result["finishedAt"] = now_iso()
            entry["result"] = result
            try:
                producer["run"] = result.get("runId") or (result.get("runDir") or "").split("/")[2] if (result.get("runDir") or "").startswith(".itailor/runs/") else result.get("runId")
                shared_store.sync(project, producer={k: v for k, v in producer.items() if v})
            except Exception as exc:  # noqa: BLE001
                publish({"type": "observe", "message": f"The shared store could not be updated: {exc}"})
            cell = None
            try:
                # Saved to disk before the run is reported as finished, so whoever sees "finished" finds the result.
                cell = projects.update_cell(pid, nid, cid, {"status": cell_status, "result": result, "steps": entry["steps"],
                                                           "runId": run_id, "finished": result["finishedAt"]}, bump_counter=True)
            except Exception as exc:  # noqa: BLE001
                publish({"type": "error", "message": f"The result could not be saved into the Patchbook: {exc}"})
            entry["status"] = cell_status
            entry["finished"] = time.time()
            try:
                activity.record(project, activity.summarize(entry, result))
            except Exception as exc:  # noqa: BLE001
                publish({"type": "observe", "message": f"The activity record could not be written: {exc}"})
            publish({"type": "patchbook_end", "message": cell_status, "status": cell_status, "runId": run_id,
                     "cell": cell, "result": result})
            close_stream()

        def run_attempt(agent, strat: str, extra: str) -> tuple[str, dict]:
            info = strategy.STRATEGIES[strat]
            eng = info["engine"]
            if eng == "quick":
                started_at = time.time()
                derived = derive_checks(agent._ensure_client(), task, project_listing(project, max_chars=1200), started_at, emit=agent.emit)
                r = agent.run_script(task, language=language, checks=checks + derived, extra_system=extra,
                                     history=history if strat == "quick" else [])
                return ("done" if r.success else "failed"), _result_quick(r, project)
            if eng == "thorough":
                agent.context_files.append({"file": "(this Patchbook)", "scope": "patchbook", "text": extra})
                r = agent.run(task, checks=checks)
                return {"succeeded": "done", "partial": "partial", "cancelled": "stopped"}.get(r.status, "failed"), _result_thorough(r, project)
            if eng == "ask":
                t = agent.run_turn(task, extra_system=extra)
                return ("stopped" if t.cancelled else ("done" if t.ok else "failed")), _result_ask(t, project)
            # code: run as it is
            lang = languages_module.choose(language, code)
            agent._ensure_manifest()
            run_dir = RunDir.create(project, "code cell " + task[:40])
            agent.current_run = run_dir
            out = runcode.run(code, lang, gate=agent._make_gate(), emit=agent.emit, cwd=project,
                              run_dir=os.path.join(run_dir.path, "code"), policy=agent.policy, python=agent.python,
                              cancel=agent.cancel_token, env=dict(agent.settings.get("env") or {}),
                              timeout=float(agent.settings.get("runTimeoutSeconds") or 180),
                              on_output=lambda chunk, stream: agent.emit("output", chunk, stream=stream))
            result = _result_code(out, code, lang, project)
            return ("done" if result["ok"] else "failed"), result

        def ask_human(evidence: str, timeout: float) -> str | None:
            attempts = entry["attempts"]
            last = next((a for a in reversed(attempts) if a.get("error")), attempts[-1] if attempts else {})
            question = (f"I tried {len(attempts)} approach{'es' if len(attempts) != 1 else ''} and the task is still not done. "
                        f"The last problem: {str(last.get('error') or last.get('status') or '')[:300]}. "
                        "Can you help? Type a hint (what to do differently, where something is, what to install), or choose an option.")
            request = ConsultRequest(question=question, options=["Try again", "Stop"], trigger="patchbook_stuck",
                                     why="every approach at this effort level failed; this may need you", context=evidence[:2000])
            publish({"type": "consult_request", "message": question, **request.payload()})
            answer = oversight.consult(request, timeout=timeout, cancel=token)
            publish({"type": "consult_answer", "message": answer or "(no answer)", "requestId": request.id, "answered": answer is not None})
            return answer

        def worker() -> None:
            entry["status"] = "running"
            final_status, final_result = "failed", None
            hints: list[str] = []
            rounds = 0
            deadline = entry["started"] + float(plan["minutes"]) * 60
            try:
                shared_store.sync(project)
                publish({"type": "patchbook_start", "message": "Starting", "engine": engine, "effort": effort, "demo": demo,
                         "approaches": [strategy.STRATEGIES[s]["label"] for s in chain]})
                while True:
                    index = 0
                    while index < len(chain):
                        strat = chain[index]
                        token.check()
                        if index > 0 and time.time() > deadline:
                            publish({"type": "observe", "message": f"The time budget of this effort level ({plan['minutes']} min) is used up; not trying further approaches."})
                            break
                        info = strategy.STRATEGIES[strat]
                        publish({"type": "patchbook_strategy", "message": f"Approach {index + 1} of {len(chain)}: {info['label']}",
                                 "strategy": strat, "index": index + 1, "total": len(chain), "label": info["label"], "engine": info["engine"],
                                 "round": rounds + 1})
                        agent = make_agent(strat)
                        evidence = strategy.evidence_block(entry["attempts"]) if info["evidence"] else ""
                        extra = compose_context(agent, project, context, engine=info["engine"], evidence=evidence, hints=hints)
                        t0 = time.time()
                        try:
                            status, result = run_attempt(agent, strat, extra)
                        except RunCancelled:
                            raise
                        except Exception as exc:  # noqa: BLE001
                            status, result = "failed", {"engine": info["engine"], "error": f"{type(exc).__name__}: {exc}"}
                            publish({"type": "error", "message": result["error"]})
                        try:
                            client = getattr(agent, "_client", None)
                            entry["model"] = "demo-model" if demo else str((client.describe() if client else {}).get("model") or entry["model"])
                        except Exception:  # noqa: BLE001
                            pass
                        # A script that found it needs a program it cannot run is not done, whatever its exit code says:
                        # the approach that can locate, install and run programs comes next, at any effort level.
                        program = strategy.needs_program(result) if info["engine"] == "quick" else None
                        if program:
                            status = "failed"
                            result["error"] = f"This approach cannot run programs, and the task needs {program}."
                            result["needsProgram"] = program
                            if not any(strategy.STRATEGIES[s]["engine"] == "thorough" for s in chain[index + 1:]):
                                chain.insert(index + 1, "thorough")
                            publish({"type": "observe", "message": f"The task needs a program ({program}). Switching to the approach that can find, install (with your permission) and run programs."})
                        entry["attempts"].append({"strategy": strat, "label": info["label"], "engine": info["engine"], "status": status,
                                                  "error": str(result.get("error") or "")[:1000], "elapsed": round(time.time() - t0, 1),
                                                  "code": str(result.get("code") or "")[:4000], "stderr": str(result.get("stderr") or "")[-2000:],
                                                  "needsProgram": program or ""})
                        final_status, final_result = status, result
                        publish({"type": "patchbook_attempt", "message": f"Approach {index + 1} {STATUS_WORD.get(status, status)}"
                                 + (f": {str(result.get('error') or '')[:160]}" if status != "done" and result.get("error") else ""),
                                 "status": status, "index": index + 1, "total": len(chain)})
                        if status in ("done", "stopped"):
                            break
                        index += 1
                    if final_status in ("done", "stopped") or token.is_cancelled:
                        break
                    if rounds >= int(plan["humanRounds"]) or time.time() > deadline:
                        break
                    rounds += 1
                    answer = ask_human(strategy.evidence_block(entry["attempts"]), float(agent.settings.get("consultTimeoutSeconds") or 600))
                    if answer is None or answer.strip().lower() in ("stop", "stop here", "no"):
                        break
                    if answer.strip().lower() not in ("try again", "retry", "yes"):
                        hints.append(answer.strip())
                    publish({"type": "patchbook_strategy", "message": "Trying again" + (" with your hint" if hints else "") + f" (round {rounds + 1})",
                             "strategy": "retry", "index": 0, "total": len(chain), "label": "Trying again", "round": rounds + 1})
            except RunCancelled:
                final_status = "stopped"
                final_result = final_result or {"error": "Stopped by user."}
            except Exception as exc:  # noqa: BLE001
                entry["error"] = f"{type(exc).__name__}: {exc}"
                publish({"type": "error", "message": entry["error"]})
                final_status, final_result = "failed", {"error": entry["error"]}
            finally:
                if final_status == "stopped" and final_result is not None:
                    final_result.setdefault("error", "Stopped by user.")
                finish(final_status, final_result)

        threading.Thread(target=worker, daemon=True, name=f"patchbook-run-{run_id}").start()
        return entry

    # ------------------------------------------------------------------
    def pending_payload(self, run_id: str, request_id: str) -> dict | None:
        entry = self.runs.get(run_id)
        if not entry or not entry.get("oversight"):
            return None
        return next((p for p in entry["oversight"].pending() if str(p.get("requestId")) == str(request_id)), None)

    def answer(self, run_id: str, request_id: str, answer) -> bool:
        entry = self.runs.get(run_id)
        if not entry or not entry.get("oversight"):
            return False
        return bool(entry["oversight"].resolve(str(request_id or ""), answer))

    def stop(self, run_id: str) -> bool:
        entry = self.runs.get(run_id)
        if not entry:
            return False
        entry["cancel"].cancel()
        return True

    def stream(self, run_id: str):
        """Server-sent events: the log so far, then live events until the run ends."""
        entry = self.runs.get(run_id)
        if not entry:
            return
        yield "retry: 3000\n\n"
        inbox: queue.Queue = queue.Queue()
        with entry["sublock"]:
            entry["subscribers"].append(inbox)
            snapshot = list(entry["log"])
            finished = entry["status"] not in ("starting", "running")
        last = snapshot[-1]["n"] if snapshot else 0
        try:
            for item in snapshot:
                yield "data: " + json.dumps(item, ensure_ascii=False, default=str) + "\n\n"
            if finished:
                yield "data: " + json.dumps({"type": "stream_end", "status": entry["status"]}) + "\n\n"
                return
            while True:
                try:
                    item = inbox.get(timeout=15)
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    yield "data: " + json.dumps({"type": "stream_end", "status": entry["status"]}) + "\n\n"
                    return
                if item.get("n", 0) <= last:
                    continue
                last = item["n"]
                yield "data: " + json.dumps(item, ensure_ascii=False, default=str) + "\n\n"
        finally:
            with entry["sublock"]:
                if inbox in entry["subscribers"]:
                    entry["subscribers"].remove(inbox)
