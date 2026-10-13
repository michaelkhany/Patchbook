# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
Running commands for the agent.

Commands are split into argv and run WITHOUT a shell, so pipes, chaining and
redirects cannot happen at all; a command that contains them is classified
as consequential (never read-only). A short list of inspection commands runs
without asking; anything else goes through the permission gate; a handful of
destructive commands are refused even when approved (``policy.HARD_BLOCK``).

From DAYA's ``agent_tools.run_shell`` and Patch Code's ``shell.js``.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import threading
import time

from ..events import CancelToken, tail
from ..policy.engine import is_destructive
from ..sandbox import child_env

SAFE_COMMANDS = {
    "ls", "dir", "pwd", "cat", "head", "tail", "wc", "find", "stat", "file", "du", "df", "echo",
    "which", "where", "whoami", "date", "env", "printenv", "uname", "type", "tree", "hostname",
    "python", "python3", "pip", "pip3", "rscript", "r", "conda", "uv", "node", "npm", "npx", "pnpm", "yarn",
    "git", "go", "cargo", "java", "javac", "dotnet", "ruby", "gem", "php", "perl", "rustc", "tsc", "gcc", "g++",
    "clang", "docker", "apptainer", "singularity", "nvidia-smi", "sinfo", "squeue", "sacct", "pandoc", "quarto",
    "ffmpeg", "ffprobe", "soffice", "libreoffice", "pdflatex", "latex", "make", "cmake", "winget", "brew", "apt",
}
SAFE_SUBCOMMANDS = {
    "pip": ["list", "show", "--version", "-V", "freeze", "check"],
    "pip3": ["list", "show", "--version", "-V", "freeze", "check"],
    "conda": ["list", "info", "--version"], "uv": ["--version", "pip"],
    "python": ["--version", "-V"], "python3": ["--version", "-V"],
    "node": ["--version", "-v"], "npm": ["--version", "-v", "ls", "list", "view", "outdated", "why", "config"],
    "npx": ["--version"], "pnpm": ["--version", "ls", "list"], "yarn": ["--version", "list", "why"],
    "git": ["status", "log", "diff", "show", "branch", "remote", "rev-parse", "ls-files", "blame", "describe",
            "tag", "config", "shortlog"],
    "go": ["version", "env", "list", "vet"], "cargo": ["--version", "metadata", "tree", "check"],
    "java": ["-version", "--version"], "javac": ["-version", "--version"],
    "dotnet": ["--version", "--info", "--list-sdks", "--list-runtimes"],
    "ruby": ["--version", "-v"], "gem": ["list", "--version"], "php": ["--version", "-v"],
    "perl": ["--version", "-v"], "rustc": ["--version"], "tsc": ["--version", "-v"],
    "gcc": ["--version"], "g++": ["--version"], "clang": ["--version"], "r": ["--version"],
    "rscript": ["--version"], "docker": ["--version", "ps", "images", "version", "info"],
    "apptainer": ["--version", "version"], "singularity": ["--version", "version"],
    "nvidia-smi": [], "sinfo": [], "squeue": [], "sacct": [],
    "pandoc": ["--version"], "quarto": ["--version", "check"], "ffmpeg": ["-version"], "ffprobe": ["-version"],
    "soffice": ["--version"], "libreoffice": ["--version"], "pdflatex": ["--version"], "latex": ["--version"],
    "make": ["--version"], "cmake": ["--version"], "winget": ["--version", "list", "search"],
    "brew": ["--version", "list", "info"], "apt": ["list", "show", "--version"],
}
SHELL_METACHARACTERS = ("&&", "||", "|", ";", ">", "<", "`", "$(", "\n", "\r")
_WIN_LAUNCHERS = {"npm", "npx", "pnpm", "yarn", "tsc", "code", "winget", "scala-cli", "quarto"}


def split_command(text: str) -> list[str]:
    """Split into argv without a shell. On Windows shlex runs in non-POSIX
    mode so ``C:\\path`` survives, and the outer quotes are stripped afterwards."""
    if os.name != "nt":
        return shlex.split(text, posix=True)
    tokens = []
    for token in shlex.split(text, posix=False):
        if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
            token = token[1:-1]
        tokens.append(token)
    return tokens


def classify(command: str) -> dict:
    """``{"readOnly": bool, "why": str, "destructive": bool}``."""
    text = str(command or "").strip()
    destructive = is_destructive(text)
    if not text:
        return {"readOnly": False, "why": "empty command", "destructive": False}
    if any(token in text for token in SHELL_METACHARACTERS):
        return {"readOnly": False, "why": "chains, pipes or redirects the output", "destructive": destructive}
    try:
        parts = split_command(text)
    except ValueError:
        return {"readOnly": False, "why": "unbalanced quotes", "destructive": destructive}
    if not parts:
        return {"readOnly": False, "why": "empty command", "destructive": False}
    program = os.path.basename(parts[0]).lower()
    for ext in (".exe", ".cmd", ".bat"):
        if program.endswith(ext):
            program = program[: -len(ext)]
    if program not in SAFE_COMMANDS:
        return {"readOnly": False, "why": f"'{program}' is not on the read-only list", "destructive": destructive}
    allowed = SAFE_SUBCOMMANDS.get(program)
    if allowed is not None and allowed:
        if len(parts) < 2 or parts[1] not in allowed:
            return {"readOnly": False, "why": f"'{program}' is only read-only for {', '.join(allowed)}",
                    "destructive": destructive}
        if program == "git" and parts[1] == "config" and not any(p in ("--get", "--list", "-l") for p in parts[2:]):
            return {"readOnly": False, "why": "git config without --get/--list writes", "destructive": destructive}
        if program == "uv" and parts[1] == "pip" and (len(parts) < 3 or parts[2] not in ("list", "show", "freeze")):
            return {"readOnly": False, "why": "uv pip is only read-only for list/show/freeze", "destructive": destructive}
    if program in ("python", "python3", "node", "ruby", "perl", "php") and any(p in ("-c", "-e") for p in parts):
        return {"readOnly": False, "why": f"{program} -c/-e runs arbitrary code", "destructive": destructive}
    return {"readOnly": True, "why": "read-only inspection", "destructive": destructive}


def _kill(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/pid", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10)
        else:
            import signal
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:  # noqa: BLE001
                proc.terminate()
        proc.wait(timeout=3)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _resolve_argv(argv: list[str]) -> list[str]:
    """Find the program; wrap Windows .cmd/.bat launchers in cmd.exe."""
    program = argv[0]
    found = shutil.which(program) or program
    if os.name == "nt":
        lower = found.lower()
        if lower.endswith((".cmd", ".bat")) or os.path.basename(program).lower() in _WIN_LAUNCHERS and not lower.endswith(".exe"):
            comspec = os.environ.get("COMSPEC", "cmd.exe")
            return [comspec, "/d", "/s", "/c", subprocess.list2cmdline([found, *argv[1:]])]
    return [found, *argv[1:]]


def run_argv(argv: list[str], *, cwd: str, timeout: float = 120.0, env: dict | None = None,
             cancel: CancelToken | None = None, on_output=None, stdin: str | None = None,
             command: str | None = None) -> dict:
    """Run one command (argv, no shell) in ``cwd``. Returns a result dict; never raises."""
    if not argv:
        return {"success": False, "exitCode": None, "stdout": "", "stderr": "", "error": "No command was given."}
    started = time.monotonic()
    merged_env = child_env(env)
    try:
        proc = subprocess.Popen(
            _resolve_argv(argv), cwd=cwd, env=merged_env,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=(os.name != "nt"),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
    except FileNotFoundError:
        return {"success": False, "exitCode": None, "stdout": "", "stderr": "",
                "error": f"Command not found: {argv[0]}", "command": command or " ".join(argv)}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "exitCode": None, "stdout": "", "stderr": "",
                "error": f"{type(exc).__name__}: {exc}", "command": command or " ".join(argv)}

    chunks = {"stdout": [], "stderr": []}

    def reader(stream, name):
        try:
            for raw in iter(lambda: stream.readline(), b""):
                text = raw.decode("utf-8", "replace")
                chunks[name].append(text)
                if on_output:
                    try:
                        on_output(text, name)
                    except Exception:  # noqa: BLE001
                        pass
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                pass

    threads = [threading.Thread(target=reader, args=(proc.stdout, "stdout"), daemon=True),
               threading.Thread(target=reader, args=(proc.stderr, "stderr"), daemon=True)]
    for thread in threads:
        thread.start()
    if stdin is not None:
        try:
            proc.stdin.write(stdin.encode("utf-8"))
            proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
    timed_out = cancelled = False
    while True:
        try:
            proc.wait(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.is_cancelled:
                cancelled = True
                _kill(proc)
                break
            if time.monotonic() - started >= timeout:
                timed_out = True
                _kill(proc)
                break
    for thread in threads:
        thread.join(timeout=2)
    stdout = tail("".join(chunks["stdout"]), 6000)
    stderr = tail("".join(chunks["stderr"]), 4000)
    code = proc.returncode
    base = {"command": command or " ".join(argv), "exitCode": code, "stdout": stdout, "stderr": stderr,
            "durationMs": round((time.monotonic() - started) * 1000)}
    if cancelled:
        return {**base, "success": False, "error": "Stopped by user.", "cancelled": True}
    if timed_out:
        return {**base, "success": False, "error": f"The command timed out after {int(timeout)}s."}
    return {**base, "success": code == 0, "error": None if code == 0 else f"Exited with code {code}."}


def run(command: str, *, cwd: str, timeout: float = 120.0, env: dict | None = None,
        cancel: CancelToken | None = None, on_output=None, stdin: str | None = None) -> dict:
    text = str(command or "").strip()
    if not text:
        return {"success": False, "exitCode": None, "stdout": "", "stderr": "", "error": "No command was given."}
    try:
        argv = split_command(text)
    except ValueError as exc:
        return {"success": False, "exitCode": None, "stdout": "", "stderr": "",
                "error": f"Could not parse the command: {exc}"}
    if not argv:
        return {"success": False, "exitCode": None, "stdout": "", "stderr": "", "error": "No command was given."}
    return run_argv(argv, cwd=cwd, timeout=timeout, env=env, cancel=cancel, on_output=on_output,
                    stdin=stdin, command=text)
