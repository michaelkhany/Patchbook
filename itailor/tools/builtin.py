# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""The default tool set, wired to their executors (Patch Code's tools/index.js, extended)."""

from __future__ import annotations

import os

from .. import languages
from ..sandbox import resolve_path
from . import envtools, fs, human, install, knowledge, runcode, shell, web
from .registry import Tool, ToolContext, ToolRegistry, bool_, int_, list_, schema, str_


def _web_allowed(ctx: ToolContext) -> bool:
    settings = ctx.settings or {}
    return settings.get("webSearch", True) is not False and (settings.get("sandbox") or {}).get("allowNetwork", True) is not False


def _read(args, ctx):
    return fs.read_file(ctx.cwd, args, confine=ctx.confine)


def _write(args, ctx):
    return fs.write_file(ctx.cwd, args, confine=ctx.confine)


def _edit(args, ctx):
    return fs.edit_file(ctx.cwd, args, confine=ctx.confine)


def _listdir(args, ctx):
    return fs.list_dir(ctx.cwd, args, confine=ctx.confine)


def _glob(args, ctx):
    return fs.glob(ctx.cwd, args, confine=ctx.confine)


def _grep(args, ctx):
    return fs.grep(ctx.cwd, args, confine=ctx.confine)


def _shell(args, ctx):
    cwd = ctx.cwd
    if args.get("cwd"):
        try:
            cwd = resolve_path(ctx.cwd, args["cwd"], confine=ctx.confine, must_exist=True)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
    timeout = max(5, min(float(args.get("timeout") or (ctx.settings or {}).get("commandTimeoutSeconds") or 120), 3600))
    return shell.run(str(args.get("command") or ""), cwd=cwd, timeout=timeout, env=ctx.env, cancel=ctx.cancel,
                     on_output=ctx.on_output)


def _runcode(args, ctx):
    timeout = float((ctx.settings or {}).get("runTimeoutSeconds") or 180)
    result = runcode.run(str(args.get("code") or ""), str(args.get("language") or "python"), gate=ctx.gate, emit=ctx.emit,
                         cwd=ctx.cwd, runs_dir=os.path.join(ctx.run_dir, "steps") if ctx.run_dir else None,
                         timeout=timeout, env=ctx.env, cancel=ctx.cancel, on_output=ctx.on_output,
                         filename=args.get("filename"), stdin=args.get("stdin"), policy=ctx.policy, python=ctx.python)
    from ..sandbox import rel_of
    return {"success": result.get("success"), "exitCode": result.get("exitCode"), "language": result.get("language"),
            "command": result.get("command"), "stdout": result.get("stdout"), "stderr": result.get("stderr"),
            "error": result.get("error"), "durationMs": result.get("durationMs"),
            "files": [rel_of(ctx.cwd, f) for f in result.get("files") or []], "notes": result.get("notes") or [],
            "scriptPath": rel_of(ctx.cwd, result["scriptPath"]) if result.get("scriptPath") else None}


def _install(args, ctx):
    result = install.install(str(args.get("manager") or "pip"), args.get("packages") or [], cwd=ctx.cwd, python=ctx.python,
                             cancel=ctx.cancel, on_output=ctx.on_output, env=ctx.env)
    return {k: result.get(k) for k in ("success", "installed", "rejected", "command", "stdout", "stderr", "error")}


def _websearch(args, ctx):
    if not _web_allowed(ctx):
        return {"error": "Web access is disabled in settings."}
    return web.search(str(args.get("query") or ""), max_results=int(args.get("max_results") or 6))


def _webfetch(args, ctx):
    if not _web_allowed(ctx):
        return {"error": "Web access is disabled in settings."}
    return web.fetch_page(str(args.get("url") or ""), max_chars=int(args.get("max_chars") or 12000))


def _knowledge(args, ctx):
    read = fs.read_file(ctx.cwd, {"path": args.get("path"), "limit": 5000}, confine=ctx.confine)
    if read.get("error"):
        return read
    if read.get("binary"):
        return {"error": "Binary file."}
    raw = "\n".join(line.split("\t", 1)[1] if "\t" in line else line for line in read["content"].split("\n"))
    lang = languages.by_filename(str(args.get("path") or ""))
    graph = knowledge.analyse(raw, lang.id if lang else "plaintext")
    return {"path": read["path"], "graph": graph, "summary": knowledge.graph_prompt(graph)}


def _project_state(args, ctx):
    graph = ctx.graph
    if graph is None:
        return {"error": "No project graph is available in this context."}
    query = str(args.get("query") or "").strip()
    out = {"summary": graph.summary(max_runs=5, max_files=30, max_decisions=15) or "(nothing recorded yet)",
           "graphPath": graph.path}
    if query:
        out["matches"] = [{"id": node_id, **{k: v for k, v in node.items() if k != "situation"}} for node_id, node in graph.find(query)]
    return out


def default_registry() -> ToolRegistry:
    tools = [
        Tool(**schema("Read", "Read a text file from the project as numbered lines. Read before you edit.",
                      {"path": str_("File path, relative to the project root."), "offset": int_("First line (1-based). Default 1."),
                       "limit": int_("How many lines. Default 2000.")}, ["path"]), execute=_read),
        Tool(**schema("Write", "Create or overwrite a file with the given content. Use Edit for small changes to an existing file.",
                      {"path": str_("File path, relative to the project root."), "content": str_("The complete file content.")},
                      ["path", "content"]), execute=_write, describe=lambda a: f"Write {a.get('path')}"),
        Tool(**schema("Edit", "Replace an exact string in a file. old_string must match exactly once unless replace_all is true.",
                      {"path": str_("File path, relative to the project root."), "old_string": str_("The exact text to replace."),
                       "new_string": str_("The replacement text."), "replace_all": bool_("Replace every occurrence. Default false.")},
                      ["path", "old_string", "new_string"]), execute=_edit, describe=lambda a: f"Edit {a.get('path')}"),
        Tool(**schema("ListDir", "List a directory as a tree (ignoring node_modules, .git, build output).",
                      {"path": str_('Directory, relative to the project root. Default ".".'), "depth": int_("Levels to show (1-6). Default 2.")}),
             execute=_listdir),
        Tool(**schema("Glob", 'Find files by glob pattern, newest first, e.g. "**/*.csv" or "src/**/*.py".',
                      {"pattern": str_("Glob pattern."), "path": str_('Directory to search. Default ".".')}, ["pattern"]), execute=_glob),
        Tool(**schema("Grep", "Search file contents with a regular expression. Returns path:line: text.",
                      {"pattern": str_("Regular expression (Python syntax)."), "path": str_('Directory or file. Default ".".'),
                       "glob": str_('Only files matching this glob, e.g. "*.py".'), "case_insensitive": bool_("Ignore case."),
                       "max_results": int_("Cap on matches (default 100)."), "context": int_("Lines of context (0-5).")}, ["pattern"]),
             execute=_grep),
        Tool(**schema("Shell", "Run ONE command in the project (no shell: no pipes, no &&, no redirects). Read-only inspections run immediately; anything else asks the user first.",
                      {"command": str_('The command line, e.g. "python -m pytest tests/".'), "reason": str_("Why you need it (shown to the user)."),
                       "timeout": int_("Seconds before the command is killed."), "cwd": str_("Subdirectory to run in, relative to the project.")},
                      ["command"]), execute=_shell, classify=lambda a: shell.classify(a.get("command")),
             describe=lambda a: f"Shell: {a.get('command')}"),
        Tool(**schema("RunCode", "Write a complete script in the given language, run it, and get stdout/stderr/exit code plus the files it produced. A missing package is installed (with permission) and the script re-run. Use it to test an idea, run an analysis, or produce files.",
                      {"language": str_("python, r, javascript, shellscript, powershell, go, … (see ENVIRONMENT for what runs here)."),
                       "code": str_("The COMPLETE, self-contained script."), "reason": str_("What the script is for (shown to the user)."),
                       "filename": str_('Optional file name for the script, e.g. "check.py".'), "stdin": str_("Optional text piped to standard input.")},
                      ["language", "code"]), execute=_runcode,
             classify=lambda a: {"readOnly": False, "destructive": False},
             describe=lambda a: f"Run {a.get('language')} script" + (f": {a.get('reason')}" if a.get("reason") else "")),
        Tool(**schema("Install", "Install packages with a package manager so the work can continue. Always asks the user first.",
                      {"manager": str_("pip, uv, npm, npm-dev, pnpm, yarn, r, gem, go, cargo, dotnet or composer."),
                       "packages": list_("Package names (optionally with version specifiers)."), "reason": str_("Why they are needed.")},
                      ["manager", "packages"]), execute=_install,
             describe=lambda a: f"Install ({a.get('manager')}): {' '.join(a.get('packages') or [])}",
             command_of=lambda a: " ".join(install.install_command(str(a.get("manager") or "pip"), a.get("packages") or []) or [])),
        Tool(**schema("WebSearch", "Search the web (DuckDuckGo, no account). Look up an API, an error message or documentation instead of guessing.",
                      {"query": str_("The search query."), "max_results": int_("1-10, default 6.")}, ["query"]),
             execute=_websearch, available=_web_allowed),
        Tool(**schema("WebFetch", "Fetch a web page or API URL and return its text (HTML converted to plain text).",
                      {"url": str_("The http(s) URL."), "max_chars": int_("Cap on the returned text (default 12000).")}, ["url"]),
             execute=_webfetch, available=_web_allowed),
        Tool(**schema("KnowledgeGraph", "What a file already defines: imports, functions with signatures, classes, variables, files it touches. Read it before adding to a file so you reuse instead of redefining.",
                      {"path": str_("File path, relative to the project root.")}, ["path"]), execute=_knowledge),
        Tool(**schema("EnvInfo", "What this machine can do: OS, hardware, interpreters, package managers, Python packages, installed applications, network. Without a section you get the summary.",
                      {"section": str_("One of: os, hardware, interpreters, packageManagers, devTools, docTools, pythonPackages, apps, network.")}),
             execute=envtools.env_info),
        Tool(**schema("FindProgram", "Is a command-line program installed? Returns its path and version, or an install hint for this OS.",
                      {"name": str_("The program name, e.g. Rscript, pandoc, docker.")}, ["name"]), execute=envtools.find_program),
        Tool(**schema("FindApp", "Find an installed application by name (Excel, RStudio, MATLAB, LibreOffice, …) with its path, version and how to drive it headless if documented.",
                      {"name": str_("Part of the application's name.")}, ["name"]), execute=envtools.find_app),
        Tool(**schema("ProjectState", "What earlier runs in this project left behind: runs and their outcomes, files produced and by which step, permission answers the user gave, open items. Query a name to find matching nodes (files, steps, decisions, lessons).",
                      {"query": str_("Optional text to search the project graph for, e.g. a file name or a tool.")}),
             execute=_project_state),
        Tool(**schema("OpenWith", "Run an installed application on a file, or headless with arguments (e.g. soffice --headless --convert-to pdf). Asks the user first.",
                      {"app": str_("Application or program name."), "path": str_("File to open, relative to the project."),
                       "args": list_("Extra command-line arguments."), "wait": bool_("Wait for it to exit (default true)."),
                       "timeout": int_("Seconds to wait.")}, ["app"]), execute=envtools.open_with, klass="system",
             describe=lambda a: f"Open with {a.get('app')}: {a.get('path') or ' '.join(a.get('args') or [])}",
             command_of=lambda a: f"{a.get('app')} {' '.join(a.get('args') or [])} {a.get('path') or ''}".strip()),
        Tool(**schema("AskUser", "Ask the human for a decision. ONLY when one of these triggers applies: ambiguous_goal (materially changes the work), irreversible_or_outward, evidence_contradicts, cost_or_risk_fork, lesson_says_ask. Routine choices are yours; state your assumption instead.",
                      {"question": str_("The question, specific and short."), "options": list_("Concrete options, if there are some."),
                       "trigger": str_("ambiguous_goal | irreversible_or_outward | evidence_contradicts | cost_or_risk_fork | lesson_says_ask"),
                       "materiality": str_("low | medium | high - how much the answer changes the work."), "why": str_("One sentence on why you cannot decide.")},
                      ["question", "trigger"]), execute=human.ask_user, klass="human",
             describe=lambda a: f"Ask the user: {str(a.get('question') or '')[:80]}"),
    ]
    return ToolRegistry(tools)
