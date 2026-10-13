# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
The ``itailor`` command.

    itailor "task"                       run a goal in the current folder, interactive oversight
    itailor --print "task"               headless: no prompts, deny by default, JSON summary on stdout
    itailor --jsonl "task"               event stream as JSON lines (what another program can drive)
    itailor script "task" [--language r] one-shot script engine
    itailor env [--refresh] [--json]     the capability manifest
    itailor model [--probe]              discovered sources, candidates and the selection with its reasons
    itailor lessons list|forget ID|propose
    itailor init [--yes] [--smoke]       discover, choose a model, write config, smoke test
    itailor doctor                       re-run discovery and probes
    itailor runs [--project DIR]         list runs; itailor report RUN_ID; itailor resume RUN_ID
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__, checks as checks_module, env as env_module, settings as settings_module
from .agent import Agent, Budgets
from .llm import discover as llm_discover, select as llm_select, providers
from .llm.client import OpenAICompatibleClient
from .oversight import AutoDeny, ConsoleOversight
from .runs import RunDir, list_runs

SUBCOMMANDS = ("run", "script", "env", "model", "lessons", "init", "doctor", "runs", "report", "resume", "graph")


def _console_renderer(verbose: bool = True):
    def render(event) -> None:
        t = event.type
        if t == "delta":
            sys.stdout.write(event.message)
            sys.stdout.flush()
            return
        if t in ("final",):
            print()
            return
        if t == "output":
            if verbose:
                sys.stdout.write(event.message)
            return
        if t == "heartbeat":
            return
        prefix = {"think": "…", "observe": "·", "tool_call": "→", "tool_result": "←", "step_start": "■", "step_done": "✓",
                  "plan": "☰", "permission_request": "?", "decision": "⚖", "consult_request": "?", "consult_answer": "!",
                  "error": "✗", "run_start": "▶", "run_end": "■", "lesson": "★", "usage": "", "route": "↪"}.get(t, "")
        if t == "usage" and not verbose:
            return
        if t == "decision" and not verbose:
            return
        if t == "tool_result" and not verbose:
            return
        print(f"{prefix} {event.message}" if event.message else f"{prefix} {t}")
    return render


def _jsonl_renderer():
    def render(event) -> None:
        if event.type == "heartbeat":
            return
        sys.stdout.write(json.dumps(event.to_dict(), ensure_ascii=False, default=str) + "\n")
        sys.stdout.flush()
    return render


def _parse_checks(specs: list[str]) -> list:
    out = []
    for spec in specs or []:
        kind, _, arg = spec.partition(":")
        if kind == "file" or kind == "file_exists":
            out.append(checks_module.file_exists(arg))
        elif kind == "stdout":
            out.append(checks_module.stdout_matches(arg))
        elif kind == "csv":
            path, _, rows = arg.partition("@")
            out.append(checks_module.csv_rows(path, int(rows or 1)))
        elif kind == "json":
            out.append(checks_module.json_valid(arg))
        elif kind == "cmd":
            out.append(checks_module.command_exit_zero(arg))
        else:
            raise SystemExit(f"unknown check '{spec}' (use file:PATH, stdout:REGEX, csv:PATH@MINROWS, json:PATH, cmd:COMMAND)")
    return out


def _agent(args, *, headless: bool, on_event) -> Agent:
    overrides = {}
    if getattr(args, "mode", None):
        overrides["permissionMode"] = args.mode
    if getattr(args, "base_url", None):
        overrides["baseUrl"] = args.base_url
    if getattr(args, "max_steps", None):
        overrides["budgets"] = {"steps": args.max_steps}
    if getattr(args, "profile", None):
        overrides["profile"] = args.profile
    if getattr(args, "local_only", False):
        overrides["privacy"] = {"localOnly": True}
    oversight = AutoDeny() if headless else ConsoleOversight()
    return Agent(args.project, model=getattr(args, "model", None), settings=overrides, oversight=oversight, on_event=on_event)


def cmd_run(args) -> int:
    headless = bool(args.print or args.jsonl)
    renderer = _jsonl_renderer() if args.jsonl else (None if args.print else _console_renderer(args.verbose))
    agent = _agent(args, headless=headless, on_event=renderer)
    try:
        result = agent.run(args.task, checks=_parse_checks(args.check))
    except KeyboardInterrupt:
        agent.cancel()
        print("\nstopped.", file=sys.stderr)
        return 130
    if args.print:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False, default=str))
    elif not args.jsonl:
        print(f"\n[{result.status}] report: {result.report_path}")
        if result.summary:
            print(result.summary)
    return 0 if result.ok else 1


def cmd_script(args) -> int:
    headless = bool(args.print or args.jsonl)
    renderer = _jsonl_renderer() if args.jsonl else (None if args.print else _console_renderer(args.verbose))
    agent = _agent(args, headless=headless, on_event=renderer)
    result = agent.run_script(args.task, language=args.language, checks=_parse_checks(args.check))
    if args.print or args.jsonl:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False, default=str))
    else:
        print(result.stdout)
        if not result.success:
            print(f"[failed] {result.error}\n{result.stderr[-2000:]}", file=sys.stderr)
        if result.files:
            print("files: " + ", ".join(result.files))
    return 0 if result.success else 1


def cmd_env(args) -> int:
    manifest = env_module.discover(args.project, refresh=args.refresh, include_apps=not args.no_apps)
    if args.json:
        print(json.dumps(manifest, indent=2, ensure_ascii=False, default=str))
    else:
        print(env_module.summary(manifest, max_apps=60))
        print(f"\n(cached: {manifest.get('cached')}; probe took {manifest.get('probeSeconds')} s; file: {env_module.discover.__module__})")
    return 0


def _gather_candidates(project: str, probe: bool, emit=print):
    sources = llm_discover.discover(project)
    usable = [s for s in sources if s.base_url and (s.api_key or s.local)]
    llm_discover.fill_models(usable)
    caps = {}
    cache_path = os.path.join(settings_module.user_dir(), "model_tool_capabilities.json")
    try:
        with open(cache_path, "r", encoding="utf-8") as handle:
            caps = json.load(handle)
    except Exception:  # noqa: BLE001
        caps = {}
    if probe:
        for source in usable:
            client = OpenAICompatibleClient(source.config())
            for model in source.models[:40]:
                key = f"{source.base_url}|{model}"
                if key in caps or providers.known_tool_support(source.base_url, model) is True:
                    continue
                emit(f"probing {model}…")
                verdict = client.probe_tool_calling(model=model)
                if verdict["verdict"] != "inconclusive":
                    caps[key] = {"nativeToolCalling": verdict["verdict"] == "supported", "detail": verdict["detail"][:200]}
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as handle:
            json.dump(caps, handle, indent=1)
    manifest = env_module.discover(project)
    candidates = llm_select.candidates_from_sources(usable, caps, env_module.machine_for_selection(manifest))
    return sources, usable, candidates


def cmd_model(args) -> int:
    sources, usable, candidates = _gather_candidates(args.project, args.probe)
    settings = settings_module.load(args.project)
    privacy = settings.get("privacy") or {}
    selection = llm_select.select(candidates, llm_select.TaskProfile(),
                                  llm_select.Constraints(local_only=bool(privacy.get("localOnly") or args.local_only),
                                                         exclude=settings.get("autoModelExclude") or []))
    if args.json:
        print(json.dumps({"sources": [s.public() for s in sources], "selection": selection.to_dict()}, indent=2, default=str))
        return 0
    print("Sources:")
    for s in sources:
        print(f"  - {s.id} [{s.kind}] {s.base_url or ''} {'(key set)' if s.api_key else ''} {s.note}"
              + (f" - {len(s.models)} model(s)" if s.models else "") + (f" - {s.message}" if s.message and not s.models else ""))
    print("\nRanking (coder role):")
    for row in selection.ranked[:15]:
        print(f"  {row['score']:.3f}  {row['model']}  ctx={row['context'] or '?'} tools={row['nativeTools']} "
              + ", ".join(f"{k}={v:.2f}" for k, v in row["criteria"].items()))
    print("\nSelection:")
    for line in selection.explanation:
        print("  " + line)
    return 0 if selection.roles else 1


def cmd_lessons(args) -> int:
    agent = Agent(args.project, discover_env=False)
    store = agent.lessons
    if args.action == "list":
        for lesson in store.all():
            print(f"{lesson.id}  [{lesson.kind}] {lesson.decision or lesson.fix[:60]}  conf={lesson.confidence:.2f}  {json.dumps(lesson.situation)[:100]}")
        if not store.all():
            print("(no lessons yet)")
    elif args.action == "forget":
        print("forgotten" if store.forget(args.id or "") else "no such lesson")
    elif args.action == "propose":
        for proposal in store.propose_rules():
            print(f"{proposal['rule']}  ->  permissions.{proposal['list']}  (from {proposal['lessonId']}, used {proposal['uses']}x)")
    elif args.action == "export":
        print(json.dumps([l.to_dict() for l in store.all()], indent=2, ensure_ascii=False))
    return 0


def cmd_init(args) -> int:
    project = os.path.abspath(args.project)
    print(f"iTailor {__version__} - initialising {project}\n")
    print("1. Discovering this machine…")
    manifest = env_module.discover(project, refresh=True)
    print(env_module.summary(manifest, max_apps=15))
    print("\n2. Looking for model sources…")
    sources, usable, candidates = _gather_candidates(project, args.probe, emit=lambda m: print("   " + m))
    for s in sources:
        print(f"   - {s.id} [{s.kind}] {s.base_url or s.note} {'(key set)' if s.api_key else ''}"
              + (f" - {len(s.models)} model(s)" if s.models else "") + (f" - {s.message}" if s.message and not s.models else ""))
    chosen_base, chosen_model, key_env = "", "", ""
    if candidates:
        selection = llm_select.select(candidates, llm_select.TaskProfile(), llm_select.Constraints(local_only=args.local_only))
        for line in selection.explanation:
            print("   " + line)
        chosen_model = selection.roles.get("coder", "")
        source_id = selection.role_sources.get("coder", "")
        source = next((s for s in usable if s.id == source_id), None)
        if source:
            chosen_base, key_env = source.base_url, source.key_env
    if not chosen_model and not args.yes:
        print("\n   No usable model source was found. Three ways forward:")
        print("   a) hosted: set an API key, e.g.  ITAILOR_BASE_URL=https://chat-ai.academiccloud.de/v1  ITAILOR_API_KEY=…")
        print("   b) local: start Ollama / LM Studio / llama-server, then run `itailor init` again")
        print("   c) plan-only: continue without a model (discovery, checks and reports still work)")
        try:
            chosen_base = input("   base URL (empty to skip): ").strip()
            if chosen_base:
                key_env = input("   environment variable holding the key (e.g. ITAILOR_API_KEY): ").strip() or "ITAILOR_API_KEY"
                chosen_model = input("   model id (empty = auto): ").strip() or "auto"
        except (EOFError, KeyboardInterrupt):
            pass
    if not chosen_model and args.yes:
        print("\n   no model: exiting non-zero (--yes never downloads or prompts)")
    print("\n3. Writing configuration…")
    if chosen_base or chosen_model:
        settings_module.write_layer(settings_module.user_config_path(),
                                    {"baseUrl": chosen_base, "model": chosen_model or "auto", "apiKeyEnv": key_env})
        print(f"   {settings_module.user_config_path()}  (key stays in {key_env or 'the environment'}; never in a file)")
    project_settings = settings_module.project_settings_path(project)
    if not os.path.exists(project_settings):
        settings_module.write_layer(project_settings, settings_module.SETTINGS_TEMPLATE)
        print(f"   {project_settings}  (starter permission policy)")
    context_file = os.path.join(project, settings_module.CONTEXT_FILENAME)
    if not os.path.exists(context_file):
        with open(context_file, "w", encoding="utf-8") as handle:
            handle.write(settings_module.CONTEXT_TEMPLATE)
        print(f"   {context_file}  (fill in what a new colleague should know)")
    gitignore = os.path.join(project, ".gitignore")
    try:
        existing = open(gitignore, "r", encoding="utf-8").read() if os.path.exists(gitignore) else ""
        if ".itailor/runs/" not in existing:
            with open(gitignore, "a", encoding="utf-8") as handle:
                handle.write("\n# iTailor\n.itailor/runs/\n.itailor/settings.local.json\n.itailor/env.json\n.itailor/scratch/\n")
            print(f"   {gitignore}  (runs and local settings ignored)")
    except OSError:
        pass
    if args.smoke and chosen_model:
        print("\n4. Smoke test: one tiny script through the full loop…")
        agent = Agent(project, oversight=AutoDeny() if args.yes else ConsoleOversight(), on_event=_console_renderer(False))
        result = agent.run_script("Print the Python version and the number of files in the current folder.", language="python")
        print("   " + ("passed" if result.success else f"failed: {result.error}"))
        return 0 if result.success else 1
    print("\nDone. Try:  itailor \"describe the files in this folder and write a short README\"")
    return 0 if (chosen_model or not args.yes) else 2


def cmd_doctor(args) -> int:
    manifest = env_module.discover(args.project, refresh=True)
    print(env_module.summary(manifest, max_apps=30))
    sources, usable, candidates = _gather_candidates(args.project, True)
    print(f"\n{len(sources)} source(s), {len(usable)} usable, {len(candidates)} candidate model(s)")
    settings = settings_module.load(args.project)
    print(f"settings layers: {[s['name'] for s in settings['_sources']]}; errors: {settings['_errors'] or 'none'}")
    return 0


def cmd_runs(args) -> int:
    for run in list_runs(args.project):
        print(f"{run['id']}  [{run['status']}]  {run['goal'][:70]}")
    return 0


def cmd_report(args) -> int:
    run_dir = RunDir.open(args.project, args.run_id)
    print(open(run_dir.report_md, "r", encoding="utf-8").read())
    return 0


def cmd_graph(args) -> int:
    from .graph import ProjectGraph, graph_path
    path = graph_path(args.project)
    g = ProjectGraph(path)
    if args.rebuild:
        g.rebuild(os.path.abspath(args.project))
        g.save()
        print(f"rebuilt from run folders -> {path}")
    if args.yaml:
        if os.path.isfile(path):
            print(open(path, "r", encoding="utf-8").read())
        else:
            print("(no graph yet)")
        return 0
    print(g.summary(max_runs=10, max_files=40, max_decisions=20) or "(nothing recorded yet)")
    print(f"\nnodes: {len(g.nodes)}, edges: {len(g.edges)}, file: {path}")
    return 0


def cmd_resume(args) -> int:
    headless = bool(args.print or args.jsonl)
    renderer = _jsonl_renderer() if args.jsonl else (None if args.print else _console_renderer(args.verbose))
    agent = _agent(args, headless=headless, on_event=renderer)
    result = agent.resume(args.run_id)
    if args.print:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False, default=str))
    return 0 if result.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="itailor", description="iTailor - the patch mechanism as a command.")
    parser.add_argument("--version", action="version", version=f"itailor {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", "-C", default=".", help="project folder (default: current)")
    common.add_argument("--mode", choices=settings_module.PERMISSION_MODES, help="permission mode")
    common.add_argument("--model", help="model id (default: auto-select)")
    common.add_argument("--base-url", help="OpenAI-compatible base URL")
    common.add_argument("--profile", help="policy profile: desktop | shared-server | ci | classroom")
    common.add_argument("--local-only", action="store_true", help="never use a remote model")
    common.add_argument("--print", action="store_true", help="headless: no prompts, JSON result on stdout")
    common.add_argument("--jsonl", action="store_true", help="headless: events as JSON lines on stdout")
    common.add_argument("--verbose", "-v", action="store_true")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", parents=[common], help="run a goal")
    run.add_argument("task")
    run.add_argument("--check", action="append", default=[], help="file:PATH | stdout:REGEX | csv:PATH@MINROWS | json:PATH | cmd:COMMAND")
    run.add_argument("--max-steps", type=int)
    run.set_defaults(func=cmd_run)
    script = sub.add_parser("script", parents=[common], help="one-shot script engine")
    script.add_argument("task")
    script.add_argument("--language", default="auto")
    script.add_argument("--check", action="append", default=[])
    script.set_defaults(func=cmd_script)
    env = sub.add_parser("env", parents=[common], help="capability manifest")
    env.add_argument("--refresh", action="store_true")
    env.add_argument("--json", action="store_true")
    env.add_argument("--no-apps", action="store_true")
    env.set_defaults(func=cmd_env)
    model = sub.add_parser("model", parents=[common], help="discovered models and the selection")
    model.add_argument("--probe", action="store_true", help="probe native tool calling for unknown models")
    model.add_argument("--json", action="store_true")
    model.set_defaults(func=cmd_model)
    lessons = sub.add_parser("lessons", parents=[common], help="lessons learned")
    lessons.add_argument("action", choices=["list", "forget", "propose", "export"])
    lessons.add_argument("id", nargs="?")
    lessons.set_defaults(func=cmd_lessons)
    init = sub.add_parser("init", parents=[common], help="set up this machine and project")
    init.add_argument("--yes", action="store_true", help="non-interactive")
    init.add_argument("--probe", action="store_true")
    init.add_argument("--smoke", action="store_true", help="run one tiny script at the end")
    init.set_defaults(func=cmd_init)
    doctor = sub.add_parser("doctor", parents=[common], help="re-run discovery and probes")
    doctor.set_defaults(func=cmd_doctor)
    runs = sub.add_parser("runs", parents=[common], help="list runs")
    runs.set_defaults(func=cmd_runs)
    rep = sub.add_parser("report", parents=[common], help="show a run's report")
    rep.add_argument("run_id")
    rep.set_defaults(func=cmd_report)
    res = sub.add_parser("resume", parents=[common], help="resume a run")
    res.add_argument("run_id")
    res.set_defaults(func=cmd_resume)
    gr = sub.add_parser("graph", parents=[common], help="the project knowledge graph (.itailor/graph.yaml)")
    gr.add_argument("--rebuild", action="store_true", help="rebuild it from the run folders")
    gr.add_argument("--yaml", action="store_true", help="print the YAML file itself")
    gr.set_defaults(func=cmd_graph)
    return parser


def main(argv: list | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `itailor "task"` without a subcommand means `itailor run "task"`.
    if argv and argv[0] not in SUBCOMMANDS and argv[0] not in ("-h", "--help", "--version"):
        argv = ["run", *argv]
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
