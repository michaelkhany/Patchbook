# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
The script runner: execute generated code in a run directory, capture
stdout/stderr/exit code, collect the files it produced, and heal a missing
dependency (install with permission, then re-run the SAME code) before the
error is handed back to the model. DAYA's ``itailor.run`` and
``_heal_missing_dependency``; Patch Code's ``runner.js``.

A generated Python script is launched through ``guard.py`` so it is held to
the sandbox policy; other languages have no equivalent hook and keep the
local-machine posture.
"""

from __future__ import annotations

import os
import sys
import time
import uuid

from .. import languages
from ..events import CancelToken
from ..policy.decisions import Action
from ..sandbox import RootsPolicy
from . import fs, install, shell

MAX_DEPENDENCY_HEALS = 3


def execute(code: str, language: str, *, cwd: str, runs_dir: str | None = None, timeout: float = 180.0,
            env: dict | None = None, cancel: CancelToken | None = None, on_output=None,
            filename: str | None = None, stdin: str | None = None, policy: RootsPolicy | None = None,
            python: str | None = None, run_dir: str | None = None) -> dict:
    lang = languages.resolve(language, filename)
    base = {"success": False, "stdout": "", "stderr": "", "exitCode": None, "files": [], "language": language}
    if not lang:
        return {**base, "error": f"Unknown language '{language}'."}
    if not lang.runnable:
        return {**base, "error": f"{lang.label} files can be edited but not executed."}
    if not languages.program_available(lang):
        return {**base, "error": f"{lang.label} needs '{lang.programs[0] if lang.programs else lang.id}' on PATH, "
                                 "which is not installed. Use FindProgram for an install hint."}
    run_dir = run_dir or os.path.join(runs_dir or os.path.join(cwd, ".itailor", "runs"), "scripts", uuid.uuid4().hex[:10])
    os.makedirs(run_dir, exist_ok=True)
    name = os.path.basename(filename) if filename else f"patch{lang.extensions[0]}"
    script_path = os.path.join(run_dir, name)
    with open(script_path, "w", encoding="utf-8") as handle:
        handle.write(str(code))
    before_run = fs.snapshot(run_dir)
    before_cwd = fs.snapshot(cwd)
    marker = time.time()
    ctx = {"platform": sys.platform, "python": python or sys.executable, "cwd": cwd}
    child_extra = dict(env or {})
    if policy is not None:
        child_extra.update(policy.child_paths())
    child_extra["ITAILOR_RUN_DIR"] = run_dir
    if lang.compile:
        exe = os.path.join(run_dir, "patch.exe" if os.name == "nt" else "patch.out")
        compiled = shell.run_argv(lang.compile(script_path, exe), cwd=run_dir, timeout=timeout, env=child_extra,
                                  cancel=cancel, on_output=on_output)
        if not compiled.get("success"):
            return {**base, "stage": "compile", "exitCode": compiled.get("exitCode"), "stdout": compiled.get("stdout", ""),
                    "stderr": compiled.get("stderr", ""), "error": compiled.get("error") or "Compilation failed.",
                    "scriptPath": script_path, "runDir": run_dir, "language": lang.id}
        argv = [exe]
    else:
        argv = lang.run(script_path, ctx)
        if not argv:
            return {**base, "error": f"No runner for {lang.label} on this platform.", "language": lang.id}
        if lang.id == "python" and policy is not None and policy.enabled:
            argv = policy.guard_argv(argv[0], script_path)
    started = time.time()
    result = shell.run_argv(argv, cwd=cwd, timeout=timeout, env=child_extra, cancel=cancel, on_output=on_output, stdin=stdin)
    skip = {name, "patch.exe", "patch.out"}
    # Produced = new in the run dir, new in the project, or modified in the project since the run started.
    files = fs.new_files(run_dir, before_run, skip) + fs.new_files(cwd, before_cwd) + fs.recently_modified(cwd, marker, skip={name})
    files = list(dict.fromkeys(f for f in files if not os.path.basename(f).startswith(".")))
    return {"success": bool(result.get("success")), "exitCode": result.get("exitCode"), "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""), "error": result.get("error"), "cancelled": result.get("cancelled", False),
            "durationMs": round((time.time() - started) * 1000), "files": files, "scriptPath": script_path,
            "runDir": run_dir, "language": lang.id, "command": " ".join(argv)}


def heal_missing_dependency(result: dict, code: str, language: str, *, gate=None, emit=None, **options) -> tuple[dict, list]:
    """Turn "No module named 'x'" into an installed x and a re-run of the same code."""
    notes: list[str] = []
    cwd = options.get("cwd") or os.getcwd()
    for _attempt in range(MAX_DEPENDENCY_HEALS):
        if result.get("success"):
            return result, notes
        blame = "\n".join(str(result.get(k) or "") for k in ("stderr", "stdout", "error"))
        missing = install.missing_module_from(blame)
        if not missing:
            return result, notes
        package = install.package_for(missing["manager"], missing["module"])
        if not install.is_installable_name(package):
            notes.append(f"'{missing['module']}' is missing, but '{package}' is not a name iTailor will install.")
            return result, notes
        argv = install.install_command(missing["manager"], [package], python=options.get("python"))
        command = " ".join(argv) if argv else f"{missing['manager']} install {package}"
        if emit:
            emit("think", f"The script needs '{package}', which isn't installed…")
        if gate is not None:
            decision = gate(Action(gate="install", tool="Install", args={"manager": missing["manager"], "packages": [package]},
                                   summary=f"Install the {missing['manager']} package '{package}'?",
                                   detail=f"The script failed with \"{missing['line']}\". Installing '{package}' lets it finish; the same code is then re-run.",
                                   command=command))
            if not decision.allowed:
                notes.append(f"Installing '{package}' was declined ({decision.reason}), so the script could not run.")
                return {**result, "error": f"{result.get('error') or ''} ('{package}' is not installed and permission to install it was declined.)".strip()}, notes
        if emit:
            emit("tool_call", f"Installing {package}…", name="Install", args={"manager": missing["manager"], "packages": [package]})
        done = install.install(missing["manager"], [package], cwd=cwd, python=options.get("python"),
                               cancel=options.get("cancel"), on_output=options.get("on_output"), env=options.get("env"))
        if not done.get("success"):
            notes.append(f"Could not install '{package}': {done.get('error') or 'the package manager failed'}.")
            if emit:
                emit("observe", f"Installing {package} failed.")
            return result, notes
        notes.append(f"Installed '{package}' and re-ran the script.")
        if emit:
            emit("observe", f"Installed {package}; re-running…")
        result = execute(code, language, **options)
    return result, notes


def run(code: str, language: str, *, gate=None, emit=None, **options) -> dict:
    """Execute, then heal missing dependencies. What the RunCode tool calls."""
    result = execute(code, language, **options)
    if result.get("cancelled"):
        return {**result, "notes": []}
    healed, notes = heal_missing_dependency(result, code, language, gate=gate, emit=emit, **options)
    return {**healed, "notes": notes}
