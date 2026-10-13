# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
The agent: the tool loop and the goal loop.

``run_turn`` is the tool loop (Patch Code's ``runTurn``): ask the model,
execute the one tool it asked for (after the gate and the hooks), hand the
result back, repeat until it answers in plain text or the step budget is
spent. Native tool calling when the model supports it, the text protocol
otherwise.

``run`` is the goal loop above it (design §2.2): understand → discover →
plan → for each step: execute (one tool-loop turn) → verify (the step's
acceptance checks) → repair or replan within budgets → report. The loop is
an explicit state machine serialised to ``state.json`` after every step, so
a run can be resumed, and everything it decides goes through the policy
engine; the model only produces candidates.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Iterator

from . import context as context_module
from . import env as env_module
from . import hooks as hooks_module
from . import languages as languages_module
from . import lessons as lessons_module
from . import planner, report as report_module, settings as settings_module, textprotocol
from .checks import Check, CheckContext, from_spec, run_checks
from .engines.script import ScriptEngine, ScriptResult
from .events import CancelToken, EventStream, RunCancelled, clip
from .graph import ProjectGraph, graph_path
from .llm import discover as llm_discover
from .llm import select as llm_select
from .llm.client import ChatClient, FakeClient, ModelConfig, OpenAICompatibleClient, ToolCall, friendly_error
from .oversight import AutoDeny, Oversight
from .permissions import Gate
from .policy.decisions import Action
from .policy.engine import PolicyEngine, default_chain, load_entry_point_deciders
from .repair import StoppingRule, error_signature
from .runs import RunDir
from .sandbox import RootsPolicy, rel_of
from .tools import ToolContext, ToolRegistry, default_registry
from .tools import shell as shell_module
from .transcript import Transcript
from .usage import UsageMeter

READ_ONLY_TOOLS = ("Read", "Glob", "Grep", "ListDir", "KnowledgeGraph", "WebSearch", "WebFetch", "EnvInfo",
                   "FindProgram", "FindApp", "ProjectState")
MAX_TOOL_RESULT_CHARS = 30000
KEEP_RECENT_TOOL_RESULTS = 8
CAPABILITY_CACHE = os.path.join(settings_module.user_dir(), "model_tool_capabilities.json")


@dataclass
class Budgets:
    steps: int = 20
    repairs_per_step: int = 3
    replans: int = 2
    minutes: float = 30.0
    tool_steps_per_step: int = 25
    tokens: int | None = None

    @classmethod
    def from_settings(cls, settings: dict) -> "Budgets":
        b = settings.get("budgets") or {}
        return cls(steps=int(b.get("steps", 20)), repairs_per_step=int(b.get("repairsPerStep", 3)),
                   replans=int(b.get("replans", 2)), minutes=float(b.get("minutes", 30)),
                   tool_steps_per_step=int(b.get("toolStepsPerStep", 25)), tokens=b.get("tokens"))


@dataclass
class TurnResult:
    ok: bool
    text: str = ""
    messages: list = field(default_factory=list)
    steps: int = 0
    error: str = ""
    cancelled: bool = False
    tool_results: list = field(default_factory=list)      # [{name, args, output, ok}]
    files: list = field(default_factory=list)


@dataclass
class RunResult:
    ok: bool
    run_id: str
    status: str
    summary: str = ""
    files: list = field(default_factory=list)
    report_path: str = ""
    plan: dict = field(default_factory=dict)
    steps: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    error: str = ""
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def _serialize(result) -> str:
    if isinstance(result, str):
        return clip(result, MAX_TOOL_RESULT_CHARS)
    try:
        return clip(json.dumps(result, indent=1, ensure_ascii=False, default=str), MAX_TOOL_RESULT_CHARS)
    except Exception:  # noqa: BLE001
        return clip(str(result), MAX_TOOL_RESULT_CHARS)


def _trim(messages: list, max_tokens: int) -> list:
    if context_module.estimate_tokens(messages) <= max_tokens:
        return messages
    out = [dict(m) for m in messages]
    seen = 0
    for i in range(len(out) - 1, 0, -1):
        m = out[i]
        is_tool = m.get("role") == "tool" or (m.get("role") == "user" and str(m.get("content", "")).startswith("<tool_result"))
        if not is_tool:
            continue
        seen += 1
        if seen <= KEEP_RECENT_TOOL_RESULTS:
            continue
        if isinstance(m.get("content"), str) and len(m["content"]) > 400:
            m["content"] = m["content"][:300] + "\n…[earlier tool result trimmed to save context]"
        if context_module.estimate_tokens(out) <= max_tokens:
            break
    return out


def _summarize(name: str, args: dict, output) -> str:
    if not isinstance(output, dict):
        return ""
    if output.get("error"):
        return f"{name}: {str(output['error'])[:200]}"
    if name == "Read":
        return f"Read {output.get('path')} ({output.get('shown')}/{output.get('totalLines')} lines)"
    if name == "Write":
        return f"{'Created' if output.get('action') == 'created' else 'Updated'} {output.get('path')} ({output.get('lines')} lines)"
    if name == "Edit":
        return f"Edited {output.get('path')} ({output.get('replaced')} replacement(s))"
    if name == "Glob":
        return f"Glob {args.get('pattern')}: {output.get('count')} file(s)"
    if name == "Grep":
        return f"Grep /{args.get('pattern')}/: {output.get('matches')} match(es) in {output.get('filesScanned')} file(s)"
    if name == "Shell":
        return f"{args.get('command')} -> exit {output.get('exitCode')}"
    if name == "RunCode":
        files = output.get("files") or []
        return f"{output.get('language')} script -> exit {output.get('exitCode')}" + (f", {len(files)} file(s) produced" if files else "")
    if name == "Install":
        return f"Installed {', '.join(output.get('installed') or []) or 'nothing'}"
    if name == "WebSearch":
        return f"WebSearch: {len(output.get('results') or [])} result(s)"
    if name == "WebFetch":
        return f"Fetched {args.get('url')}"
    if name in ("FindProgram", "FindApp"):
        return f"{name} {args.get('name')}: {'found' if output.get('found') else 'not found'}"
    if name == "AskUser":
        return "User answered" if output.get("answered") else "No answer from the user"
    return ""


class Agent:
    """One agent bound to one project folder."""

    def __init__(self, project: str = ".", *, client: ChatClient | None = None, model: ModelConfig | str | None = None,
                 settings: dict | None = None, permissions: str | None = None, oversight: Oversight | None = None,
                 budgets: Budgets | None = None, policy_engine: PolicyEngine | None = None,
                 lessons: lessons_module.LessonStore | None = None, registry: ToolRegistry | None = None,
                 on_event=None, discover_env: bool = True, profile: str | None = None, python: str | None = None) -> None:
        self.project = os.path.abspath(os.path.expanduser(project))
        os.makedirs(self.project, exist_ok=True)
        overrides = dict(settings or {})
        if permissions:
            overrides["permissionMode"] = permissions
        if profile:
            overrides["profile"] = profile
        self.settings = settings_module.load(self.project, overrides)
        self.mode = self.settings["permissionMode"]
        self.budgets = budgets or Budgets.from_settings(self.settings)
        self.events = EventStream(on_event)
        self.usage = UsageMeter()
        self.cancel_token = CancelToken()
        self.oversight = oversight if oversight is not None else AutoDeny()
        self.registry = registry or default_registry()
        self.python = python or sys.executable
        self._explicit_client = client
        self._model = model
        self._client: ChatClient | None = client
        self._tool_mode_cache: dict = {}
        self.selection = None
        self.manifest: dict = {}
        self._discover_env = discover_env
        user_lessons = os.path.join(settings_module.user_dir(), "lessons.jsonl")
        self.lessons = lessons or lessons_module.LessonStore(
            os.path.join(settings_module.project_dir(self.project), "lessons.jsonl"), user_lessons)
        sandbox_mode = (self.settings.get("sandbox") or {}).get("mode") or ""
        self.policy = RootsPolicy(self.project, project_root=self.project,
                                  scratch=os.path.join(settings_module.project_dir(self.project), "scratch"),
                                  **({"mode": sandbox_mode} if sandbox_mode else {}))
        self.policy_engine = policy_engine or PolicyEngine(default_chain(
            project_root=self.project, org_policy_path=self.settings.get("orgPolicyPath") or None,
            extra=load_entry_point_deciders()))
        self.context_files = settings_module.load_context_files(
            self.project, self.settings.get("contextFiles"), int(self.settings.get("maxContextFileBytes") or 60000))
        # The project knowledge graph: what earlier runs left behind, for the model and for the human.
        self.graph = ProjectGraph(graph_path(self.project))
        self.current_run: RunDir | None = None
        self._gate: Gate | None = None

    # ------------------------------------------------------------------
    # Plumbing
    # ------------------------------------------------------------------
    def emit(self, type: str, message: str = "", **data) -> None:
        self.events.emit(type, message, **data)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    def _ensure_manifest(self) -> dict:
        if self.manifest or not self._discover_env:
            return self.manifest
        self.emit("think", "Discovering what this machine can do…")
        self.manifest = env_module.discover(self.project, ttl_hours=float(self.settings.get("envCacheHours") or 24),
                                            include_apps=bool(self.settings.get("discoverApps", True)))
        self.emit("observe", f"Environment manifest ready ({'cached' if self.manifest.get('cached') else 'fresh'}): "
                             f"{len(self.manifest.get('interpreters') or {})} interpreters, {len(self.manifest.get('apps') or [])} apps.")
        self.graph.record_environment(self.manifest)
        return self.manifest

    def _ensure_client(self) -> ChatClient | None:
        if self._client is not None:
            return self._client
        cfg: ModelConfig | None = None
        if isinstance(self._model, ModelConfig):
            cfg = self._model
        else:
            sources = llm_discover.discover(self.project)
            wanted = self._model if isinstance(self._model, str) else None
            if not wanted and self.settings.get("model") and self.settings["model"] != settings_module.AUTO_MODEL:
                wanted = self.settings["model"]
            base_url = self.settings.get("baseUrl") or ""
            key_env = self.settings.get("apiKeyEnv") or ""
            if base_url:
                sources.insert(0, llm_discover.Source(id="settings", kind="config", base_url=base_url,
                                                      api_key=os.environ.get(key_env, "") if key_env else "",
                                                      key_env=key_env, model=wanted or "", note="from settings"))
            usable = [s for s in sources if s.base_url and (s.api_key or s.local)]
            if not usable:
                self.emit("error", "No model source found. Run `itailor init`, or set ITAILOR_BASE_URL / ITAILOR_API_KEY / ITAILOR_MODEL.")
                return None
            if wanted:
                source = usable[0]
                cfg = source.config(wanted)
            else:
                llm_discover.fill_models(usable)
                machine = env_module.machine_for_selection(self.manifest)
                candidates = llm_select.candidates_from_sources(usable, self._capabilities(), machine)
                privacy = self.settings.get("privacy") or {}
                constraints = llm_select.Constraints(local_only=bool(privacy.get("localOnly")),
                                                     max_price_out=privacy.get("maxPriceOut"),
                                                     exclude=list(self.settings.get("autoModelExclude") or []))
                bandit = None
                if self.settings.get("modelBandit"):
                    bandit = llm_select.BanditSelector(os.path.join(settings_module.project_dir(self.project), "bandit.json"))
                self.selection = llm_select.select(candidates, llm_select.TaskProfile(), constraints, bandit=bandit)
                self.emit("think", "Model selection: " + " | ".join(self.selection.explanation[:4]))
                chosen = self.selection.roles.get("coder") or self.selection.roles.get("planner")
                if not chosen:
                    self.emit("error", "No model passed the selection filters. " + "; ".join(self.selection.explanation))
                    return None
                source_id = self.selection.role_sources.get("coder") or self.selection.role_sources.get("planner")
                source = next((s for s in usable if s.id == source_id), usable[0])
                cfg = source.config(chosen)
        cfg.timeout = float(self.settings.get("modelTimeoutSeconds") or cfg.timeout)
        cfg.temperature = float(self.settings.get("temperature", cfg.temperature))
        cfg.max_tokens = int(self.settings.get("maxTokens") or cfg.max_tokens)
        self._client = OpenAICompatibleClient(cfg, on_usage=self.usage.record)
        self.emit("observe", f"Using model {cfg.model} at {cfg.base_url}")
        return self._client

    def _capabilities(self) -> dict:
        if self._tool_mode_cache:
            return self._tool_mode_cache
        try:
            with open(CAPABILITY_CACHE, "r", encoding="utf-8") as handle:
                self._tool_mode_cache = json.load(handle)
        except Exception:  # noqa: BLE001
            self._tool_mode_cache = {}
        return self._tool_mode_cache

    def _save_capabilities(self) -> None:
        try:
            os.makedirs(os.path.dirname(CAPABILITY_CACHE), exist_ok=True)
            with open(CAPABILITY_CACHE, "w", encoding="utf-8") as handle:
                json.dump(self._tool_mode_cache, handle, indent=1)
        except OSError:
            pass

    def _tool_mode(self, client: ChatClient) -> str:
        forced = str(self.settings.get("toolCalling") or "auto")
        if forced in ("native", "text"):
            return forced
        if isinstance(client, FakeClient):
            return "native" if client.native_tools else "text"
        desc = client.describe()
        key = f"{desc.get('baseUrl')}|{desc.get('model')}"
        caps = self._capabilities()
        entry = caps.get(key)
        if isinstance(entry, dict) and entry.get("nativeToolCalling") is not None:
            return "native" if entry["nativeToolCalling"] else "text"
        from .llm import providers
        known = providers.known_tool_support(desc.get("baseUrl", ""), desc.get("model", ""))
        if known is True:
            return "native"
        self.emit("think", f"Probing whether {desc.get('model')} supports native tool calling…")
        probe = client.probe_tool_calling()
        if probe["verdict"] == "inconclusive":
            self.emit("observe", f"Probe inconclusive ({probe['detail'][:120]}); assuming native tool calling.")
            return "native"
        caps[key] = {"nativeToolCalling": probe["verdict"] == "supported", "detail": probe["detail"][:200],
                     "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        self._save_capabilities()
        return "native" if probe["verdict"] == "supported" else "text"

    def _make_gate(self) -> Gate:
        if self._gate is None:
            self._gate = Gate(engine=self.policy_engine, mode=self.mode, rules=self.settings.get("permissions"),
                              oversight=self.oversight, timeout=float(self.settings.get("permissionTimeoutSeconds") or 300),
                              cancel=self.cancel_token, emit=self.emit, lessons=self.lessons, project_root=self.project,
                              profile=str(self.settings.get("profile") or "desktop"),
                              machine=env_module.machine_for_selection(self.manifest))
        return self._gate

    def _tool_context(self, step: dict | None = None) -> ToolContext:
        return ToolContext(cwd=self.project, settings=self.settings, gate=self._make_gate(), cancel=self.cancel_token,
                           emit=self.emit, confine=(self.settings.get("sandbox") or {}).get("confineToProject", True) is not False,
                           on_output=lambda chunk, stream: self.emit("output", chunk, stream=stream),
                           oversight=self.oversight, manifest=self.manifest,
                           run_dir=self.current_run.path if self.current_run else "",
                           policy=self.policy, python=self.python, lessons=self.lessons, registry=self.registry,
                           step=step or {}, env=dict(self.settings.get("env") or {}), graph=self.graph)

    def _lessons_block(self, text: str, tags: list | None = None) -> str:
        try:
            matches = self.lessons.retrieve({"text": text[:500], "goal_tags": tags or []}, k=5)
        except Exception:  # noqa: BLE001
            matches = []
        return lessons_module.prompt_block(matches)

    # ------------------------------------------------------------------
    # The tool loop
    # ------------------------------------------------------------------
    def run_turn(self, user_text: str, *, history: list | None = None, step: dict | None = None,
                 max_steps: int | None = None, extra_system: str = "", tool_names: list | None = None,
                 step_block: str = "") -> TurnResult:
        client = self._ensure_client()
        if client is None:
            return TurnResult(ok=False, error="no model configured")
        self._ensure_manifest()
        ctx = self._tool_context(step)
        tool_mode = self._tool_mode(client)
        available = self.registry.available_names(ctx)
        if self.mode == "plan":
            available = [n for n in available if n in READ_ONLY_TOOLS]
        if tool_names:
            available = [n for n in available if n in tool_names]
        specs = self.registry.specs(available)
        plain = self.registry.plain_specs(available)
        extra = "\n\n".join(part for part in (self.graph.summary(), extra_system) if part)
        system = context_module.build_system_prompt(
            cwd=self.project, settings=self.settings, mode=self.mode, tool_mode=tool_mode, tools=plain,
            env_summary=env_module.summary(self.manifest), sandbox_rules=self.policy.prompt_rules(),
            context_files=self.context_files, lessons_block=self._lessons_block(user_text, (step or {}).get("tags")),
            step_block=step_block, extra=extra)
        budget = max(8000, int(self.settings.get("contextTokens") or 60000))
        max_steps = max_steps or int(self.settings.get("maxSteps") or 40)
        messages = [{"role": "system", "content": system}, *(history or []), {"role": "user", "content": user_text}]
        result = TurnResult(ok=False)
        empty_turns = 0
        streamed = {"text": ""}

        def cancelled() -> TurnResult:
            result.cancelled = True
            result.error = "Stopped by user."
            result.messages = messages[1:]
            return result

        steps = 0
        for steps in range(max_steps):
            if self.cancel_token.is_cancelled:
                return cancelled()
            messages = _trim(messages, budget)
            self.emit("think", "Thinking…" if steps == 0 else "Deciding the next step…")
            streamed["text"] = ""

            def on_delta(delta: str) -> None:
                streamed["text"] += delta
                self.emit("delta", delta)
            reply = client.chat_with_retries(
                messages, tools=specs if tool_mode == "native" else None, tool_choice="auto",
                cancel=self.cancel_token, stream=bool(self.settings.get("streaming", True)) and tool_mode == "native",
                on_delta=on_delta if tool_mode == "native" else None,
                on_retry=lambda attempt, err: self.emit("think", "The model API is slow or busy; retrying…" if attempt == 1 else f"Still retrying the model API ({attempt})…"))
            if reply.cancelled:
                return cancelled()
            self.emit("usage", "", **self.usage.snapshot())
            if not reply.ok:
                message = friendly_error(reply.error, "running the agent")
                self.emit("error", message)
                result.error = message
                result.messages = messages[1:]
                result.steps = steps
                return result
            content = reply.text
            calls = []
            narration = content
            if tool_mode == "native" and reply.tool_calls:
                calls = reply.tool_calls
            elif content:
                parsed = textprotocol.parse(content)
                if parsed["tool_calls"]:
                    calls = [ToolCall(id=c["id"], name=c["name"], args=c["args"]) for c in parsed["tool_calls"]]
                    narration = parsed["content"]
            if not calls:
                if not content:
                    empty_turns += 1
                    messages.append({"role": "user", "content": "Your last reply was empty. Reply with your answer, or call a tool." if empty_turns >= 2 else "Continue."})
                    continue
                if not streamed["text"]:
                    self.emit("delta", content)
                messages.append({"role": "assistant", "content": content})
                self.emit("final", content)
                result.ok = True
                result.text = content
                result.messages = messages[1:]
                result.steps = steps + 1
                return result
            empty_turns = 0
            if tool_mode == "native":
                messages.append({"role": "assistant", "content": reply.message.get("content") or None,
                                 "tool_calls": [c.raw for c in calls]})
            else:
                messages.append({"role": "assistant", "content": content})
            if narration and not streamed["text"]:
                self.emit("delta", narration)
            for call in calls:
                if self.cancel_token.is_cancelled:
                    return cancelled()
                output, ok = self._execute_call(call, ctx, available)
                result.tool_results.append({"name": call.name, "args": call.args, "output": output, "ok": ok})
                if isinstance(output, dict):
                    for f in output.get("files") or []:
                        result.files.append(f)
                    if call.name == "Write" and output.get("path"):
                        result.files.append(output["path"])
                if tool_mode == "native":
                    messages.append({"role": "tool", "tool_call_id": call.id or f"call_{steps}", "name": call.name,
                                     "content": _serialize(output)})
                else:
                    messages.append({"role": "user", "content": textprotocol.format_result(call.name, output)})
        self.emit("think", f"Stopped after {max_steps} tool steps; summarising what was done.")
        summary = client.complete([*_trim(messages, budget), {"role": "user", "content":
                                   "You are out of tool steps. Summarise what you did, what is verified, and what remains, in plain text."}],
                                  cancel=self.cancel_token, temperature=0.2, max_tokens=1200)
        text = summary.text if summary.ok else f"Stopped after {max_steps} steps without a final answer."
        messages.append({"role": "assistant", "content": text})
        self.emit("final", text)
        result.ok = bool(summary.ok)
        result.text = text
        result.messages = messages[1:]
        result.steps = max_steps
        result.error = "" if summary.ok else "step budget exhausted"
        return result

    def _execute_call(self, call, ctx: ToolContext, available: list) -> tuple[dict, bool]:
        name, args = call.name, dict(call.args or {})
        tool = self.registry.get(name)
        description = self.registry.describe(name, args)
        self.emit("tool_call", description, id=getattr(call, "id", ""), name=name, args=args)

        def finish(output, ok: bool):
            self.emit("tool_result", _summarize(name, args, output) or description, name=name, ok=ok, result=output)
            return output, ok
        if not tool or name not in available:
            return finish({"error": f"Unknown tool '{name}'. Available tools: {', '.join(available)}."
                           + (" (plan mode: read-only tools only)" if self.mode == "plan" else "")}, False)
        if args.get("__parse_error"):
            return finish({"error": f"The arguments for {name} were not valid JSON: {str(args['__parse_error'])[:300]}. Send a single JSON object."}, False)
        missing = [k for k in (tool.parameters.get("required") or []) if args.get(k) in (None, "")]
        if missing:
            return finish({"error": f"{name} needs: {', '.join(missing)}."}, False)
        classification = {}
        if tool.classify:
            try:
                classification = tool.classify(args) or {}
            except Exception:  # noqa: BLE001
                classification = {}
        command = self.registry.command_of(name, args)
        paths = [str(args[k]) for k in ("path", "file", "cwd") if args.get(k)]
        if name == "Shell" and paths == [] and args.get("cwd"):
            paths = [str(args["cwd"])]
        action = Action(gate="tool", tool=name, args=args, klass=tool.klass, summary=description,
                        detail=str(args.get("reason") or classification.get("why") or ""), command=command,
                        read_only=bool(classification.get("readOnly")), destructive=bool(classification.get("destructive")),
                        paths=[os.path.join(self.project, p) for p in paths])
        verdict = ctx.gate(action) if ctx.gate else None
        if verdict is not None and not verdict.allowed:
            self.emit("observe", f"{description} - not allowed ({verdict.reason}).")
            return finish({"error": f"Permission denied for {name}: {verdict.reason}. Do not retry the same action; choose another approach or ask the user."}, False)
        pre = hooks_module.run("PreToolUse", settings=self.settings, cwd=self.project, tool_name=name,
                               payload={"args": args}, cancel=self.cancel_token)
        if pre["block"]:
            return finish({"error": f"Blocked by a PreToolUse hook: {pre['reason']}"}, False)
        try:
            output = tool.execute(args, ctx)
        except RunCancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            output = {"error": f"{type(exc).__name__}: {exc}"}
        if self.cancel_token.is_cancelled:
            return finish({"error": "Stopped by user."}, False)
        post = hooks_module.run("PostToolUse", settings=self.settings, cwd=self.project, tool_name=name,
                                payload={"args": args, "result": output}, cancel=self.cancel_token)
        if post["results"] and isinstance(output, dict):
            output = {**output, "hookOutput": "\n".join(f"{r['command']}: exit {r['exitCode']}\n{r['stdout']}\n{r['stderr']}".strip() for r in post["results"])}
        ok = not (isinstance(output, dict) and (output.get("error") or output.get("success") is False))
        line = _summarize(name, args, output)
        if line:
            self.emit("observe", line)
        return finish(output, ok)

    # ------------------------------------------------------------------
    # The goal loop
    # ------------------------------------------------------------------
    def run(self, goal: str, checks: list[Check] | None = None, *, plan: planner.Plan | dict | None = None,
            run_dir: RunDir | None = None, resume_state: dict | None = None) -> RunResult:
        started = time.time()
        run_dir = run_dir or RunDir.create(self.project, goal)
        self.current_run = run_dir
        self.events.drain()
        transcript = Transcript(run_dir.transcript_path, {"goal": goal, "project": self.project, "mode": self.mode})
        self.events.subscribe(transcript.record)

        def graph_recorder(event) -> None:
            if event.type == "decision":
                self.graph.record_decision(run_dir.id, event.data)
        self.events.subscribe(graph_recorder)
        self.graph.record_run_start(run_dir.id, goal, self.mode)
        state: dict = resume_state or {"runId": run_dir.id, "goal": goal, "status": "running", "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                       "assumptions": [], "steps": [], "artifacts": [], "openItems": [], "lessons": [],
                                       "clarifications": [], "tags": []}
        state["status"] = "running"

        def save_state() -> None:
            state["decisions"] = list(self._gate.decisions) if self._gate else []
            state["usage"] = self.usage.snapshot()
            state["elapsedSeconds"] = round(time.time() - started, 1)
            run_dir.write_json("state.json", state)

        self.emit("run_start", f"Run {run_dir.id}", runId=run_dir.id, goal=goal, project=self.project, mode=self.mode)
        result = RunResult(ok=False, run_id=run_dir.id, status="running")
        try:
            client = self._ensure_client()
            manifest = self._ensure_manifest()
            env_summary = env_module.summary(manifest)
            context_text = "\n\n".join(c["text"] for c in self.context_files)[:4000]
            self._make_gate()
            budget_deadline = started + self.budgets.minutes * 60

            def out_of_time() -> bool:
                return time.time() > budget_deadline

            # UNDERSTAND --------------------------------------------------
            the_plan: planner.Plan | None = None
            if resume_state and resume_state.get("plan"):
                the_plan = planner.Plan.from_dict(resume_state["plan"], goal=goal)
                self.emit("plan", f"Resuming plan revision {the_plan.revision}", plan=the_plan.to_dict())
            elif plan is not None:
                the_plan = plan if isinstance(plan, planner.Plan) else planner.Plan.from_dict(plan, goal=goal)
            elif client is not None:
                self.emit("think", "Understanding the goal…")
                understanding = planner.understand(client, goal, env_summary=env_summary, context=context_text,
                                                   cancel=self.cancel_token, emit=self.emit)
                state["restatement"] = understanding.get("restatement", goal)
                state["tags"] = list(understanding.get("tags") or [])
                state["assumptions"] = list(understanding.get("assumptions") or [])
                for unknown in understanding.get("unknowns") or []:
                    materiality = str(unknown.get("materiality") or "low")
                    question = str(unknown.get("question") or "")
                    from .policy.interrupt import consult_verdict
                    verdict = consult_verdict("ambiguous_goal", materiality=materiality, options=unknown.get("options") or None)
                    if not verdict["ask"] or not question:
                        continue
                    from .oversight import ConsultRequest
                    request = ConsultRequest(question=question, options=list(unknown.get("options") or []),
                                             why=f"materiality {materiality}; {verdict['reason']}", trigger="ambiguous_goal")
                    self.emit("consult_request", question, **request.payload())
                    answer = self.oversight.consult(request, timeout=float(self.settings.get("consultTimeoutSeconds") or 600),
                                                    cancel=self.cancel_token)
                    self.emit("consult_answer", answer or "(no answer)", requestId=request.id, answered=answer is not None)
                    if answer:
                        state["clarifications"].append(f"{question} -> {answer}")
                        try:
                            self.lessons.record_consult({"question": question[:200], "trigger": "ambiguous_goal",
                                                         "goal_tags": state["tags"]}, answer)
                        except Exception:  # noqa: BLE001
                            pass
                    else:
                        state["assumptions"].append(f"No answer to '{question}'; proceeding with the most conservative reading.")
            # PLAN -------------------------------------------------------
            available_languages = languages_module.available()
            if the_plan is None:
                if client is not None:
                    self.emit("think", "Drafting a plan…")
                    the_plan, error = planner.draft(client, goal, project=self.project, env_summary=env_summary,
                                                    context=context_text, available_languages=available_languages,
                                                    max_steps=self.budgets.steps, clarifications=state["clarifications"],
                                                    cancel=self.cancel_token, emit=self.emit)
                    if the_plan is None or error:
                        note = f"Planner fell back to a single step: {error}"
                        self.emit("observe", note)
                        the_plan = planner.single_step_plan(goal, note=note)
                        state["openItems"].append(note)
                else:
                    the_plan = planner.single_step_plan(goal, note="no model configured; single-step plan")
            the_plan.goal = goal
            if state.get("restatement") and not the_plan.restatement:
                the_plan.restatement = state["restatement"]
            for a in state.get("assumptions") or []:
                if a not in the_plan.assumptions:
                    the_plan.assumptions.append(a)
            self._persist_plan(run_dir, the_plan, state)
            self.graph.record_plan(run_dir.id, the_plan.to_dict())
            self.emit("plan", f"Plan with {len(the_plan.steps)} step(s) (revision {the_plan.revision})", plan=the_plan.to_dict())
            if self.settings.get("approvePlans") and not resume_state:
                decision = self._gate(Action(gate="plan", tool="", klass="plan", summary=f"Approve the plan ({len(the_plan.steps)} steps)?",
                                             detail=planner.to_markdown(the_plan)[:3000]))
                if not decision.allowed:
                    state["status"] = "plan_rejected"
                    state["error"] = decision.reason
                    raise _Stop("plan_rejected", decision.reason)
            # EXECUTE / VERIFY / REVISE ----------------------------------
            replans = 0
            while True:
                ordered, _cyclic = planner.topological_order(the_plan.steps)
                pending = [s for s in ordered if s.status in ("pending", "running")]
                if not pending:
                    break
                step = pending[0]
                if out_of_time():
                    state["openItems"].append(f"Time budget of {self.budgets.minutes} min exhausted before step {step.id}.")
                    state["status"] = "budget_exhausted"
                    break
                failed_deps = [d for d in step.depends_on if (the_plan.step(d) or planner.Step(id=d, title=d)).status in ("failed", "skipped")]
                if failed_deps:
                    step.status = "skipped"
                    step.summary = f"skipped: dependency {', '.join(failed_deps)} failed"
                    state["openItems"].append(f"Step {step.id} skipped because {', '.join(failed_deps)} failed.")
                    self._persist_plan(run_dir, the_plan, state)
                    continue
                outcome = self._execute_step(client, the_plan, step, run_dir, state)
                self._persist_plan(run_dir, the_plan, state)
                self.graph.record_step(run_dir.id, step.to_dict(), [a for a in state["artifacts"] if a.get("step") == step.id])
                save_state()
                if outcome == "failed" and replans < self.budgets.replans and client is not None and not out_of_time():
                    replans += 1
                    evidence = f"Step {step.id} ({step.title}) failed after {step.attempts} attempt(s): {step.summary}\n" + \
                        "\n".join(f"- {c.get('name')}: {c.get('detail')}" for c in step.check_results)
                    self.emit("think", f"Replanning from step {step.id} (replan {replans}/{self.budgets.replans})…")
                    revised, error = planner.draft(client, goal, project=self.project, env_summary=env_summary, context=context_text,
                                                   available_languages=available_languages, max_steps=self.budgets.steps,
                                                   clarifications=state["clarifications"], cancel=self.cancel_token,
                                                   emit=self.emit, previous=the_plan, evidence=evidence)
                    if revised is not None and not error:
                        the_plan = revised
                        self._persist_plan(run_dir, the_plan, state)
                        self.graph.record_plan(run_dir.id, the_plan.to_dict())
                        self.emit("plan", f"Revised plan (revision {the_plan.revision}) with {len(the_plan.steps)} step(s)", plan=the_plan.to_dict())
                        continue
                    state["openItems"].append(f"Replanning after step {step.id} failed: {error}")
                if outcome == "failed":
                    state["openItems"].append(f"Step {step.id} ({step.title}) failed: {step.summary}")
            # REPORT -----------------------------------------------------
            final_results = []
            if checks:
                stdout = "\n".join(s.summary for s in the_plan.steps)
                ctx = CheckContext(project=self.project, stdout=stdout, artifacts=[a["path"] for a in state["artifacts"]],
                                   shell_runner=self._gated_shell)
                final_results = run_checks(checks, ctx)
                state["finalChecks"] = [c.to_dict() for c in final_results]
                for c in final_results:
                    if not c.passed:
                        state["openItems"].append(f"Run-level check failed: {c.name}: {c.detail}")
            all_steps_ok = all(s.status == "done" for s in the_plan.steps)
            checks_ok = all(c.passed for c in final_results)
            if state["status"] == "running":
                state["status"] = "succeeded" if (all_steps_ok and checks_ok) else "partial"
            state["summary"] = self._final_summary(client, goal, the_plan, state)
            result.ok = state["status"] == "succeeded"
        except RunCancelled:
            state["status"] = "cancelled"
            state["error"] = "Stopped by user."
        except _Stop as stop:
            state["status"] = stop.status
            state["error"] = stop.reason
        except Exception as exc:  # noqa: BLE001
            state["status"] = "error"
            state["error"] = f"{type(exc).__name__}: {exc}"
            self.emit("error", state["error"])
        finally:
            state["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            state["elapsedSeconds"] = round(time.time() - started, 1)
            if self.selection is not None:
                state["models"] = dict(self.selection.roles)
            elif self._client is not None:
                state["models"] = {"all": self._client.describe().get("model", "")}
            save_state()
            md, _js = report_module.write(run_dir, state)
            result.status = state["status"]
            result.summary = str(state.get("summary") or "")
            result.files = [a["path"] for a in state.get("artifacts") or []]
            result.report_path = md
            result.plan = (run_dir.read_json("plan.json") or {})
            result.steps = list(state.get("steps") or [])
            result.checks = list(state.get("finalChecks") or [])
            result.usage = self.usage.snapshot()
            result.error = str(state.get("error") or "")
            result.elapsed_seconds = state["elapsedSeconds"]
            for lesson in state.get("lessons") or []:
                self.graph.record_lesson(lesson, run_dir.id)
            self.graph.record_run_end(run_dir.id, state["status"], str(state.get("summary") or ""), state.get("openItems"))
            try:
                self.graph.save()
            except Exception:  # noqa: BLE001 - the graph is derived data; never lose a run over it
                pass
            self.emit("run_end", f"{state['status']}: {state.get('summary', '')[:200]}", runId=run_dir.id,
                      status=state["status"], reportPath=md, files=result.files, graphPath=self.graph.path)
            self.events.unsubscribe(transcript.record)
            self.events.unsubscribe(graph_recorder)
        return result

    def _persist_plan(self, run_dir: RunDir, the_plan: planner.Plan, state: dict) -> None:
        run_dir.write_json("plan.json", the_plan.to_dict())
        run_dir.write_text("plan.md", planner.to_markdown(the_plan))
        state["plan"] = the_plan.to_dict()
        state["restatement"] = the_plan.restatement
        state["steps"] = [s.to_dict() for s in the_plan.steps]

    def _gated_shell(self, command: str) -> dict:
        classification = shell_module.classify(command)
        decision = self._gate(Action(gate="tool", tool="Shell", args={"command": command}, klass="shell",
                                     summary=f"Run check command: {command}", command=command,
                                     read_only=bool(classification["readOnly"]), destructive=bool(classification["destructive"])))
        if not decision.allowed:
            return {"success": False, "error": f"not allowed: {decision.reason}", "exitCode": None}
        return shell_module.run(command, cwd=self.project, timeout=float(self.settings.get("commandTimeoutSeconds") or 120),
                                cancel=self.cancel_token)

    def _step_block(self, the_plan: planner.Plan, step: planner.Step, state: dict) -> str:
        done = [s for s in the_plan.steps if s.status == "done"]
        lines = [f"PLAN (revision {the_plan.revision}) - you are executing step {step.id} of {len(the_plan.steps)}:"]
        for s in the_plan.steps:
            marker = ">>" if s.id == step.id else "  "
            lines.append(f"{marker} {s.id} [{s.status}] {s.title}")
        if done:
            lines.append("\nRESULTS SO FAR:")
            for s in done:
                lines.append(f"- {s.id}: {clip(s.summary, 300)}" + (f" (files: {', '.join(s.artifacts[:6])})" if s.artifacts else ""))
        if state.get("clarifications"):
            lines.append("\nCLARIFICATIONS FROM THE USER:\n- " + "\n- ".join(state["clarifications"]))
        lines.append(f"\nTHIS STEP: {step.title}\n{step.instruction}")
        if step.inputs:
            lines.append(f"inputs: {', '.join(step.inputs)}")
        if step.outputs:
            lines.append(f"outputs you must leave behind: {', '.join(step.outputs)}")
        lines.append(f"ACCEPTANCE CHECK (evaluated by a program after you finish; you cannot change it): {json.dumps(step.check)}")
        lines.append("Do only this step. When it is done and verified, reply with a short plain-text summary of what you did and the files you produced.")
        return "\n".join(lines)

    def _execute_step(self, client, the_plan: planner.Plan, step: planner.Step, run_dir: RunDir, state: dict) -> str:
        step.status = "running"
        self.emit("step_start", f"Step {step.id}: {step.title}", stepId=step.id, title=step.title, kind=step.kind, check=step.check)
        if step.kind == "checkpoint":
            from .oversight import ConsultRequest
            request = ConsultRequest(question=f"Checkpoint '{step.title}': {step.instruction}\nContinue?",
                                     options=["continue", "stop"], why="the plan asked for a human review here", trigger="irreversible_or_outward")
            self.emit("consult_request", request.question, **request.payload())
            answer = self.oversight.consult(request, timeout=float(self.settings.get("consultTimeoutSeconds") or 600), cancel=self.cancel_token)
            self.emit("consult_answer", answer or "(no answer)", requestId=request.id, answered=answer is not None)
            if answer and answer.strip().lower() not in ("stop", "no", "n", "abort"):
                step.status, step.summary = "done", f"reviewed: {answer}"
                state["clarifications"].append(f"Checkpoint {step.id}: {answer}")
            else:
                step.status, step.summary = "failed", "no approval at the checkpoint"
            self.emit("step_done", step.summary, stepId=step.id, status=step.status)
            return step.status
        if client is None:
            step.status, step.summary = "failed", "no model configured"
            self.emit("step_done", step.summary, stepId=step.id, status=step.status)
            return "failed"
        checks = [c for c in [from_spec(step.check)] if c is not None]
        rule = StoppingRule(max_attempts=self.budgets.repairs_per_step + 1)
        history: list = []
        evidence = ""
        first_failure = ""
        step_started = time.time()
        for attempt in range(1, self.budgets.repairs_per_step + 2):
            step.attempts = attempt
            prompt = step.instruction if attempt == 1 else (
                "The acceptance check for this step FAILED after your last attempt:\n" + evidence +
                "\nRead the real output, fix the actual defect (do not change the check), run again, and verify before replying.")
            turn = self.run_turn(prompt, history=history, step=step.to_dict(), max_steps=self.budgets.tool_steps_per_step,
                                 step_block=self._step_block(the_plan, step, state))
            if turn.cancelled:
                raise RunCancelled("Run stopped by user.")
            history = turn.messages
            for f in turn.files:
                absolute = f if os.path.isabs(f) else os.path.join(self.project, f)
                collected = run_dir.collect_artifact(absolute, step.id)
                if collected and collected["path"] not in [a["path"] for a in state["artifacts"]]:
                    state["artifacts"].append(collected)
                if collected and collected["path"] not in step.artifacts:
                    step.artifacts.append(collected["path"])
            stdout = "\n".join(str((r["output"] or {}).get("stdout") or "") for r in turn.tool_results
                               if isinstance(r["output"], dict) and r["name"] in ("RunCode", "Shell", "OpenWith"))
            stderr = "\n".join(str((r["output"] or {}).get("stderr") or "") for r in turn.tool_results
                               if isinstance(r["output"], dict) and r["name"] in ("RunCode", "Shell"))
            exit_codes = [(r["output"] or {}).get("exitCode") for r in turn.tool_results
                          if isinstance(r["output"], dict) and r["name"] in ("RunCode", "Shell")]
            last_exit = exit_codes[-1] if exit_codes else (0 if turn.ok else 1)
            ctx = CheckContext(project=self.project, stdout=stdout + "\n" + turn.text, stderr=stderr, exit_code=last_exit,
                               artifacts=step.artifacts, shell_runner=self._gated_shell, since=step_started)
            results = run_checks(checks, ctx) if checks else []
            step.check_results = [r.to_dict() for r in results]
            failed = [r for r in results if not r.passed]
            if turn.ok and not failed:
                step.status = "done"
                step.summary = clip(turn.text, 600)
                if attempt > 1 and first_failure:
                    try:
                        lesson = self.lessons.record_repair(
                            {"signature": first_failure, "step": step.title, "goal_tags": list(state.get("tags") or []) + list(step.tags),
                             "os": self.manifest.get("os", {}).get("system", "")}, clip(turn.text, 400))
                        state["lessons"].append({"kind": "repair", "text": f"{first_failure[:80]} -> {clip(turn.text, 120)}", "id": lesson.id})
                        self.emit("lesson", f"remembered a repair for '{first_failure[:60]}'", lessonId=lesson.id, kind="repair")
                    except Exception:  # noqa: BLE001
                        pass
                self.emit("step_done", f"Step {step.id} done ({attempt} attempt(s))", stepId=step.id, status="done", attempts=attempt,
                          checks=step.check_results)
                return "done"
            evidence = "\n".join(f"- {r.name}: {r.detail}" for r in failed) if failed else f"- the turn ended without a result: {turn.error or 'no final answer'}"
            signature = error_signature("CheckFailed", " ".join(r.name for r in failed) or (turn.error or "no-answer"), "check")
            if not first_failure:
                first_failure = signature + " :: " + evidence[:120]
            rule.record(signature)
            self.emit("observe", f"Step {step.id} not verified: {evidence[:200]}")
            stop, why = rule.should_stop()
            if stop:
                step.summary = f"{evidence[:300]} (stopped: {why})"
                break
            step.summary = evidence[:300]
        step.status = "failed"
        self.emit("step_done", f"Step {step.id} failed: {step.summary[:200]}", stepId=step.id, status="failed", attempts=step.attempts,
                  checks=step.check_results)
        return "failed"

    def _final_summary(self, client, goal: str, the_plan: planner.Plan, state: dict) -> str:
        done = [s for s in the_plan.steps if s.status == "done"]
        if client is None:
            return "\n".join(f"{s.id}: {s.summary}" for s in done) or "No model was configured; nothing was executed."
        material = "\n".join(f"- {s.id} [{s.status}] {s.title}: {clip(s.summary, 500)}" for s in the_plan.steps)
        files = ", ".join(a["path"] for a in state.get("artifacts") or []) or "none"
        reply = client.complete([
            {"role": "system", "content": "You write the findings section of a run report: plain language, specific numbers and file names, "
                                          "what was verified and what was not, no fluff. Under 250 words."},
            {"role": "user", "content": f"GOAL: {goal}\n\nSTEPS:\n{material}\n\nFILES PRODUCED: {files}\n\nOPEN ITEMS: {state.get('openItems') or 'none'}"}],
            cancel=self.cancel_token, temperature=0.2, max_tokens=800)
        if reply.ok and reply.text:
            return reply.text
        return "\n".join(f"{s.id}: {s.summary}" for s in done)

    # ------------------------------------------------------------------
    # Conveniences
    # ------------------------------------------------------------------
    def stream(self, goal: str, checks: list[Check] | None = None, **kwargs) -> Iterator:
        """Run in a background thread and yield events as they happen."""
        holder: dict = {}

        def worker() -> None:
            try:
                holder["result"] = self.run(goal, checks, **kwargs)
            except Exception as exc:  # noqa: BLE001
                holder["error"] = exc
                self.emit("run_end", f"error: {exc}", status="error")
        threading.Thread(target=worker, daemon=True).start()
        for event in self.events.iter(heartbeat=15.0):
            yield event
            if event.type == "run_end":
                break
            if event.type == "heartbeat" and "error" in holder:
                break
        if "error" in holder:
            raise holder["error"]
        self.result = holder.get("result")

    def resume(self, run_id: str) -> RunResult:
        run_dir = RunDir.open(self.project, run_id)
        state = run_dir.read_json("state.json") or {}
        if not state:
            raise FileNotFoundError(f"run {run_id} has no state.json")
        for s in (state.get("plan") or {}).get("steps") or []:
            if s.get("status") in ("running", "failed", "skipped"):
                s["status"] = "pending"
                s["attempts"] = 0
        state["openItems"] = []
        return self.run(state.get("goal", ""), run_dir=run_dir, resume_state=state)

    def run_script(self, task: str, *, language: str = "auto", checks: list[Check] | None = None, **kwargs) -> ScriptResult:
        client = self._ensure_client()
        if client is None:
            return ScriptResult(success=False, language=language, error="no model configured")
        self._ensure_manifest()
        run_dir = self.current_run or RunDir.create(self.project, task)
        engine = ScriptEngine(client, cwd=self.project, runs_dir=run_dir.path, policy=self.policy, gate=self._make_gate(),
                              emit=self.emit, cancel=self.cancel_token, settings=self.settings, python=self.python,
                              env_summary=env_module.summary(self.manifest), extra_env=dict(self.settings.get("env") or {}))
        return engine.run(task, language=language, checks=checks, **kwargs)

    def chat(self, text: str, history: list | None = None) -> TurnResult:
        return self.run_turn(text, history=history)


class _Stop(Exception):
    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


def run_script(task: str, *, project: str = ".", language: str = "auto", client: ChatClient | None = None,
               model: ModelConfig | str | None = None, oversight: Oversight | None = None, **kwargs) -> ScriptResult:
    """One-shot: write a script for ``task``, run it, repair it, return the result."""
    agent = Agent(project, client=client, model=model, oversight=oversight)
    return agent.run_script(task, language=language, **kwargs)
