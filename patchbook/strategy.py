# Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
Effort and strategy: what Patchbook does when one approach does not reach the goal.

iTailor's engines each have their own, deliberate stopping rules (the script
engine stops when the same failure comes back unchanged; the goal loop stops
when its budgets are spent). Patchbook sits above them and decides what to try
next: repair, rethink with the evidence of what failed, plan step by step,
replan, and finally ask the human. How far that goes is the **effort** the user
sets. Nothing here changes the library.
"""

from __future__ import annotations

import inspect
import json
import re

# The one-script approach runs in a sandbox that cannot start other programs. When a task needs one,
# the script says so with this marker (the prompt asks for it), or iTailor's guard refuses the attempt:
# the library classifies that refusal as a failure of kind "sandbox", and its message carries the phrase
# below. A script that catches the refusal and prints it leaves only that phrase behind, so the phrase is
# matched too; ``library_self_check`` confirms at start-up that the vendored library still uses it.
PROGRAM_MARKER = "NEEDS_EXTERNAL_PROGRAM:"
SANDBOX_REFUSAL = "may not start another process"
SANDBOX_FAILURE_KIND = "sandbox"


def library_self_check() -> list[str]:
    """What Patchbook relies on in the library copy, verified rather than assumed. Returns warnings."""
    warnings: list[str] = []
    try:
        from itailor import guard, repair
        if SANDBOX_REFUSAL not in inspect.getsource(guard):
            warnings.append("The iTailor copy no longer refuses process starts with the phrase Patchbook recognises "
                            f"('{SANDBOX_REFUSAL}'); tasks that need a program will only be detected through the "
                            f"'{PROGRAM_MARKER}' protocol. Update patchbook/strategy.py to the library's new wording.")
        if SANDBOX_FAILURE_KIND not in getattr(repair, "KINDS", ()):
            warnings.append("The iTailor copy no longer classifies sandbox refusals as a failure kind Patchbook recognises.")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Patchbook could not verify its assumptions about the iTailor copy: {exc}")
    return warnings
QUICK_PROTOCOL = (
    "THIS SCRIPT RUNS IN A SANDBOX THAT CANNOT START OTHER PROGRAMS: no subprocess, no shell commands, no external tools "
    "(compilers, LaTeX, converters, command-line utilities). If the task needs one, do not try to call it and do not work "
    f"around it: print exactly '{PROGRAM_MARKER} <program name>' as the first line, print one sentence saying what it is "
    "needed for, and exit with code 0. Patchbook then switches to the approach that can locate, install (with the user's "
    "permission) and run programs."
)

EFFORTS: dict = {
    "low": {
        "id": "low", "label": "Low", "quickIters": 3, "chain": ["quick"], "minutes": 5, "humanRounds": 0,
        "budgets": {"steps": 10, "repairsPerStep": 2, "replans": 1, "minutes": 5},
        "description": "One script and a few repairs. Fast; stops at the first dead end.",
    },
    "normal": {
        "id": "normal", "label": "Normal", "quickIters": 6, "chain": ["quick", "rethink"], "minutes": 15, "humanRounds": 0,
        "budgets": {"steps": 15, "repairsPerStep": 3, "replans": 2, "minutes": 15},
        "description": "A script with repairs; if that dead-ends, a different approach that knows what failed.",
    },
    "high": {
        "id": "high", "label": "High", "quickIters": 8, "chain": ["quick", "rethink", "thorough"], "minutes": 30, "humanRounds": 1,
        "budgets": {"steps": 20, "repairsPerStep": 4, "replans": 3, "minutes": 30},
        "description": "Script, then a different approach, then a step-by-step plan with verified steps. Asks you once if still stuck.",
    },
    "max": {
        "id": "max", "label": "Maximum", "quickIters": 10, "chain": ["quick", "rethink", "thorough", "thorough-rethink"], "minutes": 90, "humanRounds": 3,
        "budgets": {"steps": 30, "repairsPerStep": 6, "replans": 4, "minutes": 90},
        "description": "Everything above, a second plan that knows what failed, and up to three rounds of asking you for a hint. Stops only when the goal is reached, you stop it, or the problem needs you.",
    },
}
ORDER = ["low", "normal", "high", "max"]
DEFAULT = "normal"

STRATEGIES: dict = {
    "quick": {"engine": "quick", "label": "One script, repaired until it works", "evidence": False},
    "rethink": {"engine": "quick", "label": "A different approach, knowing what failed", "evidence": True},
    "thorough": {"engine": "thorough", "label": "Step by step: plan, run and verify each step", "evidence": True},
    "thorough-rethink": {"engine": "thorough", "label": "A different plan, knowing what failed", "evidence": True},
    "ask": {"engine": "ask", "label": "An answer in conversation", "evidence": False},
    "code": {"engine": "code", "label": "Your code, run as it is", "evidence": False},
}


def normalize(effort) -> str:
    key = str(effort or "").strip().lower()
    return key if key in EFFORTS else DEFAULT


def effort_plan(effort: str, overrides: dict | None = None) -> dict:
    """The plan for an effort level: the built-in table, adjusted by ``effortOverrides`` from Patchbook's
    configuration (for example ``{"high": {"quickIters": 12, "minutes": 60}}``). Unknown strategies are dropped."""
    plan = json.loads(json.dumps(EFFORTS[normalize(effort)]))
    custom = (overrides or {}).get(plan["id"]) if isinstance(overrides, dict) else None
    if isinstance(custom, dict):
        for key in ("quickIters", "minutes", "humanRounds"):
            if isinstance(custom.get(key), (int, float)):
                plan[key] = custom[key]
        if isinstance(custom.get("budgets"), dict):
            plan["budgets"].update({k: v for k, v in custom["budgets"].items() if isinstance(v, (int, float))})
        if isinstance(custom.get("chain"), list):
            chain = [s for s in custom["chain"] if s in STRATEGIES]
            if chain:
                plan["chain"] = chain
    return plan


def public(overrides: dict | None = None) -> list[dict]:
    plans = [effort_plan(k, overrides) for k in ORDER]
    return [{"id": e["id"], "label": e["label"], "description": e["description"], "steps": len(e["chain"]),
             "asksYou": e["humanRounds"] > 0, "minutes": e["minutes"]} for e in plans]


def chain_for(engine: str, effort: str, overrides: dict | None = None) -> list[str]:
    """The approaches tried in order, for a cell that starts with ``engine``."""
    plan = effort_plan(effort, overrides)
    if engine == "quick":
        return list(plan["chain"])
    if engine == "thorough":
        return ["thorough"] + (["thorough-rethink"] if "thorough-rethink" in plan["chain"] or normalize(effort) in ("high", "max") else [])
    return [engine]


def settings_for(strategy: str, effort: str, overrides: dict | None = None) -> dict:
    """iTailor settings overrides for one attempt (merged by the library's settings layers)."""
    plan = effort_plan(effort, overrides)
    out: dict = {"budgets": dict(plan["budgets"])}
    if STRATEGIES.get(strategy, {}).get("engine") == "quick":
        out["maxIterations"] = int(plan["quickIters"])
    return out


def needs_program(result: dict) -> str | None:
    """The deterministic signal that a task needs a program the script sandbox cannot run.

    Three sources, in order: the marker the script was asked to print; the library's own classification
    of the last attempt (a failure of kind "sandbox" whose message is the process-start refusal); and, for a
    script that caught the refusal and merely printed it, the refusal phrase in its output. The program's
    name comes from the marker, or from the usual "<name> not found" wording of the output."""
    text = "\n".join(str(result.get(k) or "") for k in ("stdout", "stderr", "error"))
    match = re.search(re.escape(PROGRAM_MARKER) + r"[ \t]*([^\n]+)", text)
    if match:
        return match.group(1).strip().strip("'\"`")[:80] or "an external program"
    refused = any(f.get("kind") == SANDBOX_FAILURE_KIND and SANDBOX_REFUSAL in str(f.get("emsg") or "")
                  for f in (result.get("failures") or []) if isinstance(f, dict))
    if refused or SANDBOX_REFUSAL in text:
        named = re.search(r"['\"`]?([A-Za-z0-9_.+-]+)['\"`]?\s+(?:not found in PATH|is not recognized|was not found|not found)", text)
        return named.group(1) if named else "an external program"
    return None


def program_guidance(program: str) -> str:
    """Told to the approach that can run programs. The install hint comes from the library's own table for this
    operating system (or its generic package-manager search), not from Patchbook."""
    hint = ""
    try:
        from itailor.env import install_hint
        hint = str(install_hint(program) or "").strip()
    except Exception:  # noqa: BLE001
        hint = ""
    return (f"PROGRAM NEEDED: {program}. The one-script approach cannot start programs; this approach can. "
            "Use FindProgram to locate it (it also returns an install hint for this operating system). If it is missing, install it: "
            "the Install tool for language packages, or the platform's package manager through the Shell tool for applications"
            + (f" (for this machine, for example: {hint})" if hint else "") +
            "; every such command asks the user for permission first, and if the user declines, say exactly what to install by hand "
            "and stop. Then run the program through the Shell tool and verify that the file it should produce exists.")


def evidence_block(attempts: list) -> str:
    """What earlier approaches on this task tried and why they failed, for the next approach."""
    failed = [a for a in attempts if a.get("status") != "done"]
    if not failed:
        return ""
    lines = ["EARLIER APPROACHES ON THIS SAME TASK FAILED. Do not repeat them; take a genuinely different route "
             "(another method, library, tool or language if that helps), and check the assumption that broke them:"]
    for index, attempt in enumerate(failed, 1):
        lines.append(f"Approach {index} ({attempt.get('label', attempt.get('strategy', ''))}): {attempt.get('status')}."
                     + (f" Problem: {str(attempt.get('error') or '')[:500]}" if attempt.get("error") else ""))
        stderr = str(attempt.get("stderr") or "").strip()
        if stderr:
            lines.append("  Last error output: " + " ".join(stderr[-700:].split()))
        code = str(attempt.get("code") or "")
        if code:
            head = "\n".join(code.splitlines()[:30])
            lines.append("  Its code began:\n" + "\n".join("    " + line for line in head.splitlines()))
    program = next((a.get("needsProgram") for a in reversed(failed) if a.get("needsProgram")), None)
    if program:
        lines.append("")
        lines.append(program_guidance(program))
    return "\n".join(lines)


def hints_block(hints: list) -> str:
    if not hints:
        return ""
    return "HINTS FROM THE USER (follow them):\n" + "\n".join(f"- {h}" for h in hints)
