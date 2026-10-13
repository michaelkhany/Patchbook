# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""Environment tools: EnvInfo, FindProgram, FindApp, OpenWith (design §2.3)."""

from __future__ import annotations

import os
import subprocess

from ..env import discover as env
from ..sandbox import child_env, resolve_path
from . import shell
from .registry import ToolContext


def env_info(args: dict, ctx: ToolContext) -> dict:
    manifest = ctx.manifest or env.discover(ctx.cwd)
    section = str(args.get("section") or "").strip()
    if not section:
        return {"summary": env.summary(manifest), "sections": [k for k in manifest if k not in ("schemaVersion",)]}
    if section not in manifest:
        return {"error": f"Unknown section '{section}'. Sections: {', '.join(manifest)}"}
    value = manifest[section]
    if section == "apps":
        return {"apps": [{"name": a["name"], "version": a.get("version", ""), "exe": a.get("exe", "")} for a in value][:200],
                "count": len(value)}
    return {section: value}


def find_program(args: dict, ctx: ToolContext) -> dict:
    return env.find_program(str(args.get("name") or ""))


def find_app(args: dict, ctx: ToolContext) -> dict:
    return env.find_app(str(args.get("name") or ""), ctx.manifest or None)


def open_with(args: dict, ctx: ToolContext) -> dict:
    """Launch a file in an application, or run the application headless with arguments."""
    app = str(args.get("app") or "").strip()
    path = str(args.get("path") or "").strip()
    extra = [str(a) for a in (args.get("args") or [])]
    wait = bool(args.get("wait", True))
    if not app:
        return {"error": "app is required."}
    exe = ""
    program = env.find_program(app)
    if program.get("found"):
        exe = program["path"]
    else:
        found = env.find_app(app, ctx.manifest or None)
        for match in found.get("matches") or []:
            if match.get("exe"):
                exe = match["exe"]
                break
        if not exe:
            return {"error": f"'{app}' is not installed or has no launchable executable. "
                             + (f"Install hint: {found.get('installHint')}" if found.get("installHint") else "")}
    argv = [exe, *extra]
    if path:
        try:
            absolute = resolve_path(ctx.cwd, path, confine=ctx.confine, must_exist=True)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
        argv.append(absolute)
    if wait:
        timeout = float(args.get("timeout") or (ctx.settings or {}).get("commandTimeoutSeconds") or 120)
        return shell.run_argv(argv, cwd=ctx.cwd, timeout=timeout, cancel=ctx.cancel, on_output=ctx.on_output, env=ctx.env)
    try:
        proc = subprocess.Popen(argv, cwd=ctx.cwd, env=child_env(ctx.env), stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=(os.name != "nt"))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Could not launch {exe}: {exc}"}
    return {"success": True, "launched": argv, "pid": proc.pid, "note": "started without waiting"}
