# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
iTailor - the patch mechanism as a library.

    import itailor
    agent = itailor.Agent(".")
    result = agent.run("merge the CSVs in data/ and plot monthly totals",
                       checks=[itailor.checks.file_exists("monthly_totals.png")])
    print(result.summary, result.report_path)

A natural-language request becomes code or a command that is written, run
against the real environment, read back from its actual output, verified by
checks it did not write, and repaired until it works. Deterministic methods
decide, gate, verify and stop; the model only produces candidates.
"""

__version__ = "0.1.0"

from . import checks, env, lessons, planner, policy, settings, yamllite
from .agent import Agent, Budgets, RunResult, TurnResult, run_script
from .engines.script import ScriptEngine, ScriptResult
from .events import CancelToken, Event, EventStream, RunCancelled
from .graph import ProjectGraph, graph_path
from .lessons import Lesson, LessonStore
from .llm.client import FakeClient, ModelConfig, OpenAICompatibleClient, Reply, tool_call_message
from .oversight import (AutoDeny, CallbackOversight, ConsoleOversight, ConsultRequest, PermissionRequest,
                        QueueOversight)
from .permissions import Gate
from .planner import Plan, Step
from .runs import RunDir, list_runs
from .sandbox import RootsPolicy, child_env
from .tools import Tool, ToolContext, ToolRegistry, default_registry

__all__ = [
    "__version__", "Agent", "Budgets", "RunResult", "TurnResult", "run_script", "ScriptEngine", "ScriptResult",
    "CancelToken", "Event", "EventStream", "RunCancelled", "Lesson", "LessonStore", "FakeClient", "ModelConfig",
    "OpenAICompatibleClient", "Reply", "tool_call_message", "AutoDeny", "CallbackOversight", "ConsoleOversight",
    "ConsultRequest", "PermissionRequest", "QueueOversight", "Gate", "Plan", "Step", "RunDir", "list_runs",
    "RootsPolicy", "child_env", "Tool", "ToolContext", "ToolRegistry", "default_registry",
    "ProjectGraph", "graph_path",
    "checks", "env", "lessons", "planner", "policy", "settings", "yamllite",
]
