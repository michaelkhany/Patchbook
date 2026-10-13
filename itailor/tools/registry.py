# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
The tool registry: every tool the agent can call, with its JSON schema (sent
to models with native tool calling, rendered as text otherwise), its
permission class, and its executor.

Executors receive ``(args, ctx)`` where ``ctx`` is a ``ToolContext``. A tool
may declare ``available(ctx)`` so that tools whose backing program is absent
are not advertised to the model (design §2.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..events import CancelToken
from ..policy.decisions import TOOL_CLASS


def schema(name: str, description: str, properties: dict | None = None, required: list | None = None) -> dict:
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": required or [],
                           "additionalProperties": False}}


def str_(description: str) -> dict:
    return {"type": "string", "description": description}


def int_(description: str) -> dict:
    return {"type": "integer", "description": description}


def bool_(description: str) -> dict:
    return {"type": "boolean", "description": description}


def list_(description: str, item_type: str = "string") -> dict:
    return {"type": "array", "items": {"type": item_type}, "description": description}


@dataclass
class ToolContext:
    cwd: str
    settings: dict = field(default_factory=dict)
    gate: Callable | None = None                 # gate(Action) -> Decision
    cancel: CancelToken | None = None
    emit: Callable | None = None                 # emit(type, message="", **data)
    confine: bool = True
    on_output: Callable | None = None            # on_output(chunk, stream)
    oversight: Any = None
    manifest: dict = field(default_factory=dict)
    run_dir: str = ""
    policy: Any = None                           # sandbox.RootsPolicy
    python: str = ""
    lessons: Any = None                          # lessons.LessonStore
    registry: Any = None
    step: dict = field(default_factory=dict)     # the plan step being executed, if any
    env: dict = field(default_factory=dict)      # extra environment for children
    graph: Any = None                            # graph.ProjectGraph

    def say(self, type: str, message: str = "", **data) -> None:
        if self.emit:
            try:
                self.emit(type, message, **data)
            except Exception:  # noqa: BLE001
                pass


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    execute: Callable[[dict, ToolContext], dict]
    klass: str = ""
    classify: Callable[[dict], dict] | None = None
    describe: Callable[[dict], str] | None = None
    command_of: Callable[[dict], str] | None = None
    available: Callable[[ToolContext], bool] | None = None

    def __post_init__(self) -> None:
        if not self.klass:
            self.klass = TOOL_CLASS.get(self.name, "shell")

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}

    def openai_spec(self) -> dict:
        return {"type": "function", "function": self.spec()}


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def available_names(self, ctx: ToolContext) -> list[str]:
        out = []
        for name, tool in self._tools.items():
            try:
                if tool.available is None or tool.available(ctx):
                    out.append(name)
            except Exception:  # noqa: BLE001
                continue
        return out

    def specs(self, names: list[str] | None = None) -> list[dict]:
        return [t.openai_spec() for n, t in self._tools.items() if names is None or n in names]

    def plain_specs(self, names: list[str] | None = None) -> list[dict]:
        return [t.spec() for n, t in self._tools.items() if names is None or n in names]

    def describe(self, name: str, args: dict | None) -> str:
        tool = self.get(name)
        args = args or {}
        if not tool:
            return name
        if tool.describe:
            try:
                return tool.describe(args)
            except Exception:  # noqa: BLE001
                return name
        subject = args.get("path") or args.get("pattern") or args.get("query") or args.get("url") or ""
        return f"{name} {subject}".strip()

    def command_of(self, name: str, args: dict | None) -> str:
        tool = self.get(name)
        args = args or {}
        if tool and tool.command_of:
            try:
                return tool.command_of(args)
            except Exception:  # noqa: BLE001
                return ""
        if name == "Shell":
            return str(args.get("command") or "")
        if name == "RunCode":
            return f"{args.get('language') or ''} script ({len(str(args.get('code') or '').splitlines())} lines)"
        return ""
