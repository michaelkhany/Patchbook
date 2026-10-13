# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
The system prompt, assembled fresh for every run from what is true right
now: the project, the environment manifest, the permission mode, the sandbox
rules, the user's ITAILOR.md files, retrieved lessons, the plan step - and,
in text mode, the tool protocol.
"""

from __future__ import annotations

import time

from . import languages, textprotocol

IDENTITY = """You are iTailor, an autonomous agent built on Michael Bidollahkhani's patch mechanism: a natural-language request becomes code or a command that is written, RUN against the real environment, read back from its actual output, and repaired until it works. Never hand the user code you could have verified but did not.

You can read and edit files, run commands and scripts in any language this machine has, install packages (with permission), search the web, find installed programs and applications and drive them headless, and ask the human only when a decision is genuinely theirs."""

METHOD = """HOW TO WORK
- Understand before changing: Read the files involved (or their KnowledgeGraph) before you Edit them. Never guess file contents.
- Check what the machine has before assuming it: ENVIRONMENT below lists interpreters, packages and applications; FindProgram/FindApp answer specific questions and give install hints.
- Verify: after a change run the relevant test, script or command and read the real output. When something fails, read the real error, fix the actual defect, and run again. Never hide failures behind try/except and never replace real work with a stub.
- A missing library is not a coding mistake: use Install (or let RunCode heal it) rather than rewriting around it - unless the user declined, in which case solve it in code and do not ask again.
- Use WebSearch/WebFetch to look up an API or an error instead of guessing.
- One tool call at a time; wait for its result. Narrate briefly what you are doing and why.
- Make routine decisions yourself and state the assumption. Call AskUser only for the five triggers it documents.
- Save every result the user would want as a file with a descriptive name in the project; print a short plain-language summary of findings.
- When the task is done, reply with a plain-language summary of what you did, how you verified it, what files you produced (path), and anything you could not do. Reference files as path:line.
- Refuse destructive actions (deleting the repository, wiping disks, force-pushing) and say so plainly."""


def permission_note(mode: str) -> str:
    return {
        "plan": "PERMISSION MODE: plan. You may only READ (Read, Glob, Grep, ListDir, KnowledgeGraph, EnvInfo, FindProgram, FindApp, WebSearch, WebFetch). Produce a concrete plan; do not edit or run anything.",
        "acceptEdits": "PERMISSION MODE: acceptEdits. File edits are applied without asking; commands, scripts, installs and application launches still ask the user.",
        "bypassPermissions": "PERMISSION MODE: bypassPermissions. Nothing asks the user. Be careful.",
    }.get(mode, "PERMISSION MODE: default. Read-only tools run immediately; edits, commands, scripts, installs and application launches pause and ask the user (allow once / always / deny). A denied request is final for this run - respect it and choose another approach.")


def build_system_prompt(*, cwd: str, settings: dict, mode: str, tool_mode: str, tools: list[dict],
                        env_summary: str = "", sandbox_rules: str = "", context_files: list | None = None,
                        lessons_block: str = "", step_block: str = "", extra: str = "") -> str:
    parts = [IDENTITY]
    parts.append("ENVIRONMENT\n" + f"- Project root (working directory): {cwd}\n- Date: {time.strftime('%Y-%m-%d')}\n"
                 + f"- Languages that can run here now: {', '.join(languages.available())}. Every other language can be read and edited.\n"
                 + (env_summary or ""))
    parts.append(METHOD)
    parts.append(permission_note(mode))
    if sandbox_rules:
        parts.append(sandbox_rules.strip())
    if (settings.get("sandbox") or {}).get("confineToProject", True):
        parts.append("The file tools are confined to the project folder; paths outside it are refused. Commands run without a shell: no pipes, no &&, no redirects - one command per Shell call.")
    for item in context_files or []:
        parts.append(f"PROJECT INSTRUCTIONS from {item['file']} ({item['scope']}) - follow them:\n{item['text'].strip()}")
    if lessons_block:
        parts.append(lessons_block.strip())
    if step_block:
        parts.append(step_block.strip())
    if extra:
        parts.append(extra.strip())
    if tool_mode == "text":
        parts.append(textprotocol.instructions(tools or []))
    return "\n\n".join(parts)


def estimate_tokens(messages: list) -> int:
    """Rough estimate (4 characters per token) for context trimming."""
    chars = 0
    for message in messages or []:
        content = message.get("content")
        chars += len(content) if isinstance(content, str) else len(str(content or ""))
        if message.get("tool_calls"):
            chars += len(str(message["tool_calls"]))
    return (chars + 3) // 4
