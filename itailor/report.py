# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""The run report: goal, what was done, findings, verified checks, artifacts, open items, decisions, lessons."""

from __future__ import annotations

import json
import time


def build_markdown(state: dict) -> str:
    lines = [f"# iTailor report - {state.get('runId', '')}", "",
             f"**Goal:** {state.get('goal', '')}", "",
             f"**Status:** {state.get('status', '')}" + (f" - {state.get('error')}" if state.get("error") else ""), ""]
    if state.get("restatement"):
        lines += [f"**Understood as:** {state['restatement']}", ""]
    if state.get("summary"):
        lines += ["## Findings", "", str(state["summary"]).strip(), ""]
    if state.get("assumptions"):
        lines += ["## Assumptions and clarifications", ""] + [f"- {a}" for a in state["assumptions"]] + [""]
    steps = state.get("steps") or []
    if steps:
        lines += ["## Steps", "", "| Step | Status | Attempts | Check | Result |", "| --- | --- | --- | --- | --- |"]
        for s in steps:
            checks = s.get("check_results") or []
            verdict = "passed" if checks and all(c.get("passed") for c in checks) else ("failed" if checks else "-")
            detail = "; ".join(c.get("detail", "") for c in checks)[:120]
            lines.append(f"| {s.get('id')} {s.get('title', '')} | {s.get('status')} | {s.get('attempts', 0)} | "
                         f"{(s.get('check') or {}).get('type', '')} {verdict} | {detail or s.get('summary', '')[:120]} |")
        lines.append("")
    final_checks = state.get("finalChecks") or []
    if final_checks:
        lines += ["## Run-level checks", ""] + [f"- {'PASS' if c.get('passed') else 'FAIL'} {c.get('name')}: {c.get('detail')}" for c in final_checks] + [""]
    artifacts = state.get("artifacts") or []
    if artifacts:
        lines += ["## Files produced", ""] + [f"- `{a.get('path')}` ({a.get('size', 0)} bytes, step {a.get('step') or '-'})" for a in artifacts] + [""]
    open_items = state.get("openItems") or []
    if open_items:
        lines += ["## Not done / open items", ""] + [f"- {item}" for item in open_items] + [""]
    decisions = state.get("decisions") or []
    if decisions:
        lines += ["## Permission decisions", ""] + [
            f"- {d.get('tool') or d.get('gate')}: **{d.get('decision')}** ({d.get('source')}) `{(d.get('command') or '')[:80]}`" for d in decisions] + [""]
    lessons = state.get("lessons") or []
    if lessons:
        lines += ["## Lessons recorded", ""] + [f"- [{l.get('kind')}] {l.get('text')}" for l in lessons] + [""]
    usage = state.get("usage") or {}
    if usage:
        lines += ["## Cost", "", f"- model calls: {usage.get('calls', 0)} ({usage.get('unreportedCalls', 0)} without usage data)",
                  f"- tokens: {usage.get('totalTokens', 0)} ({usage.get('promptTokens', 0)} in, {usage.get('completionTokens', 0)} out)",
                  f"- wall time: {state.get('elapsedSeconds', 0)} s", ""]
    models = state.get("models") or {}
    if models:
        lines += ["## Models", ""] + [f"- {role}: {model}" for role, model in models.items()] + [""]
    lines += ["---", f"Generated {time.strftime('%Y-%m-%d %H:%M:%S')} by iTailor. Transcript: transcript.jsonl in this folder."]
    return "\n".join(lines)


def build_json(state: dict) -> dict:
    return {"schemaVersion": "1.0", "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **state}


def write(run_dir, state: dict) -> tuple[str, str]:
    run_dir.write_text("report.md", build_markdown(state))
    with open(run_dir.report_json, "w", encoding="utf-8") as handle:
        json.dump(build_json(state), handle, indent=2, ensure_ascii=False, default=str)
    return run_dir.report_md, run_dir.report_json
