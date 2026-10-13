# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
The one-shot script engine: the original iTailor loop.

Given a task, ask the model for ONE complete self-contained script, run it
as a real subprocess in the project, read the real output, and on failure
classify it (package → install with permission and re-run the same code;
sandbox refusal by a library → stop; otherwise → hand the error back to the
model for a complete corrected script) until it exits clean, the stopping
rule fires, or the user stops it. Optional acceptance checks are run after
a clean exit; a failed check is evidence for another revision.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from .. import languages
from ..checks import Check, CheckContext, run_checks
from ..events import CancelToken, RunCancelled, clip
from ..repair import StoppingRule, classify_failure, extract_code, error_signature
from ..tools import runcode


@dataclass
class ScriptResult:
    success: bool
    language: str
    code: str = ""
    stdout: str = ""
    stderr: str = ""
    files: list = field(default_factory=list)
    iterations: int = 0
    attempts: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    error: str | None = None
    run_dir: str = ""
    stop_reason: str = ""

    def to_dict(self) -> dict:
        return {"success": self.success, "language": self.language, "code": self.code, "stdout": self.stdout,
                "stderr": self.stderr, "files": list(self.files), "iterations": self.iterations,
                "attempts": list(self.attempts), "notes": list(self.notes), "checks": list(self.checks),
                "error": self.error, "runDir": self.run_dir, "stopReason": self.stop_reason}


def system_prompt(language: str, *, env_summary: str = "", sandbox_rules: str = "", extra: str = "") -> str:
    lang = languages.by_id(language) or languages.BY_ID["python"]
    runtime = {
        "python": "You write Python 3. pandas, numpy, matplotlib and the packages listed in ENVIRONMENT are available. For charts use matplotlib with the Agg backend and savefig('name.png').",
        "r": "You write R. Load data with read.csv(...); use base R plus installed packages (ggplot2, dplyr if listed). Save plots with ggsave('name.png', ...) or png(); dev.off().",
        "javascript": "You write a Node.js script (CommonJS). Only built-in modules and packages already installed are available.",
    }.get(lang.id, f"You write a complete {lang.label} program.")
    return (
        "You are iTailor, an autonomous coding agent. Given a task you write ONE complete, self-contained script that "
        "performs it and PRINTS a concise, plain-language summary of the findings to stdout (that printed summary is what "
        f"the user sees). {runtime} The working directory is the project folder; open the user's files by the relative "
        "paths shown and save any tables, charts, models or reports there with clear, human-readable names. "
        "If a package is missing, use it anyway: iTailor installs it (with permission) and re-runs your script. "
        "Do not access the network unless the task needs it.\n\n"
        + (f"ENVIRONMENT:\n{env_summary}\n\n" if env_summary else "") + (sandbox_rules + "\n" if sandbox_rules else "")
        + (extra + "\n\n" if extra else "")
        + f"Reply with the FULL script inside a single fenced code block (```{lang.fence} … ```) and nothing else - no prose "
          "before or after. If you are later shown an execution error, reply again with the COMPLETE corrected script in the same way."
    )


class ScriptEngine:
    def __init__(self, client, *, cwd: str, runs_dir: str | None = None, policy=None, gate=None, emit=None,
                 cancel: CancelToken | None = None, settings: dict | None = None, python: str | None = None,
                 env_summary: str = "", extra_env: dict | None = None) -> None:
        self.client = client
        self.cwd = os.path.abspath(cwd)
        self.runs_dir = runs_dir or os.path.join(self.cwd, ".itailor", "runs")
        self.policy = policy
        self.gate = gate
        self.emit = emit or (lambda *a, **k: None)
        self.cancel = cancel
        self.settings = settings or {}
        self.python = python
        self.env_summary = env_summary
        self.extra_env = extra_env or {}

    def run(self, task: str, *, language: str = "auto", checks: list[Check] | None = None, max_iters: int | None = None,
            timeout: float | None = None, extra_system: str = "", history: list | None = None) -> ScriptResult:
        lang_id = languages.choose(language, task)
        lang = languages.by_id(lang_id) or languages.BY_ID["python"]
        max_iters = max_iters or int(self.settings.get("maxIterations") or 6)
        timeout = timeout or float(self.settings.get("runTimeoutSeconds") or 180)
        result = ScriptResult(success=False, language=lang.id)
        if not languages.program_available(lang):
            result.error = f"{lang.label} is not installed on this machine ('{lang.programs[0] if lang.programs else lang.id}' is not on PATH)."
            return result
        sandbox_rules = self.policy.prompt_rules() if self.policy is not None else ""
        convo = [{"role": "system", "content": system_prompt(lang.id, env_summary=self.env_summary,
                                                             sandbox_rules=sandbox_rules, extra=extra_system)}]
        for item in (history or [])[-6:]:
            if item.get("task"):
                convo.append({"role": "user", "content": f"Earlier task: {str(item['task'])[:600]}"})
            if item.get("code"):
                convo.append({"role": "assistant", "content": f"```{lang.fence}\n{str(item['code'])[:1500]}\n```"})
        convo.append({"role": "user", "content": "Task: " + str(task).strip()})
        rule = StoppingRule(max_attempts=max(1, max_iters))
        code = ""
        run_dir = os.path.join(self.runs_dir, "scripts", f"{int(time.time())}-{os.getpid()}")
        result.run_dir = run_dir
        for iteration in range(1, max(1, max_iters) + 1):
            if self.cancel is not None:
                self.cancel.check()
            result.iterations = iteration
            self.emit("think", f"iTailor is writing {lang.label} code…" if iteration == 1 else "iTailor is reading the error and fixing the code…")
            reply = self.client.chat_with_retries(convo, cancel=self.cancel, max_tokens=int(self.settings.get("maxTokens") or 4000))
            if reply.cancelled:
                raise RunCancelled("Run stopped by user.")
            if not reply.ok or not reply.text:
                result.error = "iTailor couldn't get code from the model: " + (reply.error or "no response")
                return result
            new_code = extract_code(reply.text, lang.fence)
            if not new_code:
                convo += [{"role": "assistant", "content": reply.text[:1500]},
                          {"role": "user", "content": "Reply with the full script in a single fenced code block only."}]
                continue
            code = new_code
            result.code = code
            self.emit("tool_call", f"Running the {lang.label} script…", name="RunCode", args={"language": lang.id, "lines": len(code.splitlines())})
            attempt_dir = os.path.join(run_dir, f"attempt-{iteration}")
            run = runcode.run(code, lang.id, gate=self.gate, emit=self.emit, cwd=self.cwd, run_dir=attempt_dir,
                              timeout=timeout, env=self.extra_env, cancel=self.cancel, policy=self.policy, python=self.python)
            if run.get("cancelled"):
                raise RunCancelled("Run stopped by user.")
            result.notes.extend(n for n in run.get("notes") or [] if n not in result.notes)
            failure = classify_failure(run.get("stdout", ""), run.get("stderr", ""), run.get("exitCode"), error=run.get("error") or "")
            result.stdout, result.stderr = run.get("stdout", ""), run.get("stderr", "")
            result.files = [f for f in run.get("files") or [] if os.path.isfile(f)]
            attempt_record = {"iteration": iteration, "exitCode": run.get("exitCode"), "failure": failure.to_dict(),
                              "durationMs": run.get("durationMs"), "files": len(result.files)}
            if run.get("success"):
                check_results = []
                if checks:
                    ctx = CheckContext(project=self.cwd, stdout=result.stdout, stderr=result.stderr,
                                       exit_code=run.get("exitCode"), artifacts=result.files)
                    check_results = run_checks(checks, ctx)
                    result.checks = [c.to_dict() for c in check_results]
                failed = [c for c in check_results if not c.passed]
                if not failed:
                    result.success = True
                    result.error = None
                    attempt_record["checks"] = "passed" if checks else "none"
                    result.attempts.append(attempt_record)
                    self.emit("observe", "The script ran and every check passed." if checks else "The script ran cleanly.")
                    return result
                attempt_record["checks"] = [c.to_dict() for c in failed]
                result.attempts.append(attempt_record)
                evidence = "The script exited cleanly but these acceptance checks FAILED (you may not change the checks):\n" + \
                    "\n".join(f"- {c.name}: {c.detail}" for c in failed) + "\n\nStdout was:\n" + clip(result.stdout, 1500)
                signature = error_signature("CheckFailed", " ".join(c.name for c in failed), "check")
            else:
                result.attempts.append(attempt_record)
                self.emit("observe", f"The script failed ({failure.kind}: {failure.etype or 'exit ' + str(run.get('exitCode'))}); revising…")
                if not failure.repairable:
                    result.error = f"Not repairable in code: {failure.note or failure.emsg}"
                    result.stop_reason = "unrepairable"
                    return result
                if failure.kind == "package" and any("declined" in n for n in result.notes):
                    convo += [{"role": "assistant", "content": f"```{lang.fence}\n{code}\n```"},
                              {"role": "user", "content": f"The package '{failure.module}' is NOT installed and the user declined to install it. "
                                                          "Rewrite the COMPLETE script without that package (standard library or packages listed in ENVIRONMENT only)."}]
                    rule.record(failure.signature)
                    stop, why = rule.should_stop()
                    if stop:
                        result.error = f"Stopped: {why}"
                        result.stop_reason = why
                        return result
                    continue
                evidence = ("The script failed with this error:\n" + clip(run.get("stderr") or run.get("stdout") or run.get("error") or "(no output)", 2500)
                            + (f"\nTHE FILE EXISTS UNDER A DIFFERENT NAME? Check the project listing before guessing paths." if failure.kind == "file" else ""))
                signature = failure.signature
            rule.record(signature)
            stop, why = rule.should_stop()
            if stop:
                result.error = f"Stopped: {why}"
                result.stop_reason = why
                return result
            convo += [{"role": "assistant", "content": f"```{lang.fence}\n{code}\n```"},
                      {"role": "user", "content": evidence + "\nReturn the COMPLETE corrected script in a single fenced code block. "
                                                  "If a library is genuinely missing rather than misused, keep using it - it will be installed."}]
        result.error = result.error or "The script did not complete successfully."
        result.stop_reason = result.stop_reason or "attempt budget spent"
        return result
