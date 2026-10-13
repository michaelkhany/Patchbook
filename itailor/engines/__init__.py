# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""Execution engines. ``script`` is the one-shot loop; the persistent-kernel and program-mode engines are Phase 2."""

from .script import ScriptEngine, ScriptResult, system_prompt

__all__ = ["ScriptEngine", "ScriptResult", "system_prompt"]
