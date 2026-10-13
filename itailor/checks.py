# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
Acceptance checks: the oracle a step is judged by (design §2.5, §11.2).

A check is authored by the user, by the plan before the step runs, or by a
deterministic builder; the repair loop may not edit it. Exit code 0 is
necessary, never sufficient.

Kinds: ``file_exists``, ``file_min_bytes``, ``stdout_matches``,
``stdout_not_matches``, ``exit_zero``, ``csv_rows``, ``json_valid``,
``command_exit_zero``, ``determinism`` (re-run yields the same output) and
``custom`` (a Python callable). ``from_spec`` builds one from the JSON a
plan carries.
"""

from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass, field
from typing import Callable

from .sandbox import resolve_path


@dataclass
class CheckContext:
    project: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    artifacts: list = field(default_factory=list)
    shell_runner: Callable | None = None       # shell_runner(command) -> result dict (goes through the gate)
    rerun: Callable | None = None              # rerun() -> result dict, for determinism checks
    since: float | None = None                 # when the step started; 'fresh' checks require writes after it


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    kind: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "detail": self.detail, "kind": self.kind}


@dataclass
class Check:
    name: str
    kind: str
    fn: Callable[[CheckContext], CheckResult]
    params: dict = field(default_factory=dict)

    def run(self, ctx: CheckContext) -> CheckResult:
        try:
            result = self.fn(ctx)
        except Exception as exc:  # noqa: BLE001 - a broken check fails, never crashes the run
            result = CheckResult(self.name, False, f"check raised {type(exc).__name__}: {exc}")
        result.kind = result.kind or self.kind
        return result

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, **self.params}


def _resolve(ctx: CheckContext, path: str) -> str:
    return resolve_path(ctx.project, path, confine=False)


def file_exists(path: str, min_bytes: int = 1, fresh: bool = False) -> Check:
    """``fresh=True`` additionally requires the file to have been written during
    the step (modification time after ``ctx.since``), so a leftover from an
    earlier run cannot satisfy a step that was supposed to produce it."""
    def fn(ctx: CheckContext) -> CheckResult:
        absolute = _resolve(ctx, path)
        if not os.path.isfile(absolute):
            return CheckResult(f"file_exists {path}", False, f"{path} does not exist")
        size = os.path.getsize(absolute)
        if size < min_bytes:
            return CheckResult(f"file_exists {path}", False, f"{path} is {size} bytes (< {min_bytes})")
        if fresh and ctx.since and os.path.getmtime(absolute) < ctx.since - 1:
            return CheckResult(f"file_exists {path}", False, f"{path} exists but was not written during this step (stale)")
        return CheckResult(f"file_exists {path}", True, f"{path} exists ({size} bytes)")
    return Check(f"file_exists {path}", "file_exists", fn, {"path": path, "min_bytes": min_bytes, "fresh": fresh})


def stdout_matches(pattern: str, flags: int = re.IGNORECASE | re.MULTILINE) -> Check:
    regex = re.compile(pattern, flags)

    def fn(ctx: CheckContext) -> CheckResult:
        ok = bool(regex.search(ctx.stdout or ""))
        return CheckResult(f"stdout_matches /{pattern}/", ok, "matched" if ok else "no match in stdout")
    return Check(f"stdout_matches /{pattern}/", "stdout_matches", fn, {"pattern": pattern})


def stdout_not_matches(pattern: str, flags: int = re.IGNORECASE | re.MULTILINE) -> Check:
    regex = re.compile(pattern, flags)

    def fn(ctx: CheckContext) -> CheckResult:
        hit = regex.search((ctx.stdout or "") + "\n" + (ctx.stderr or ""))
        return CheckResult(f"stdout_not_matches /{pattern}/", not hit, f"found '{hit.group(0)}'" if hit else "absent")
    return Check(f"stdout_not_matches /{pattern}/", "stdout_not_matches", fn, {"pattern": pattern})


def exit_zero() -> Check:
    def fn(ctx: CheckContext) -> CheckResult:
        return CheckResult("exit_zero", ctx.exit_code == 0, f"exit code {ctx.exit_code}")
    return Check("exit_zero", "exit_zero", fn)


def csv_rows(path: str, min_rows: int = 1, columns: list | None = None) -> Check:
    def fn(ctx: CheckContext) -> CheckResult:
        absolute = _resolve(ctx, path)
        if not os.path.isfile(absolute):
            return CheckResult(f"csv_rows {path}", False, f"{path} does not exist")
        with open(absolute, "r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, [])
            rows = sum(1 for _ in reader)
        missing = [c for c in (columns or []) if c not in header]
        if missing:
            return CheckResult(f"csv_rows {path}", False, f"missing columns {missing}; header {header[:12]}")
        ok = rows >= min_rows
        return CheckResult(f"csv_rows {path}", ok, f"{rows} data rows, header {header[:12]}")
    return Check(f"csv_rows {path}", "csv_rows", fn, {"path": path, "min_rows": min_rows, "columns": columns or []})


def json_valid(path: str, required_keys: list | None = None) -> Check:
    def fn(ctx: CheckContext) -> CheckResult:
        absolute = _resolve(ctx, path)
        if not os.path.isfile(absolute):
            return CheckResult(f"json_valid {path}", False, f"{path} does not exist")
        with open(absolute, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        missing = [k for k in (required_keys or []) if not (isinstance(data, dict) and k in data)]
        return CheckResult(f"json_valid {path}", not missing, f"missing keys {missing}" if missing else "valid JSON")
    return Check(f"json_valid {path}", "json_valid", fn, {"path": path, "required_keys": required_keys or []})


def command_exit_zero(command: str) -> Check:
    def fn(ctx: CheckContext) -> CheckResult:
        if not ctx.shell_runner:
            return CheckResult(f"command {command}", False, "no shell runner available for this check")
        result = ctx.shell_runner(command)
        ok = bool(result.get("success"))
        tail = (result.get("stderr") or result.get("stdout") or result.get("error") or "")[-300:]
        return CheckResult(f"command {command}", ok, f"exit {result.get('exitCode')}: {tail}".strip())
    return Check(f"command {command}", "command_exit_zero", fn, {"command": command})


def determinism(normalise: Callable[[str], str] | None = None) -> Check:
    """Re-run the step and compare stdout (after normalisation). A result that
    changes between identical runs is not a result."""
    def fn(ctx: CheckContext) -> CheckResult:
        if not ctx.rerun:
            return CheckResult("determinism", False, "no rerun available")
        second = ctx.rerun()
        norm = normalise or (lambda s: re.sub(r"\d+\.\d{3,}", lambda m: m.group(0)[:6], s))
        same = norm(ctx.stdout or "") == norm(str(second.get("stdout") or ""))
        return CheckResult("determinism", same, "identical output on re-run" if same else "output differs between runs")
    return Check("determinism", "determinism", fn)


def custom(fn: Callable[[CheckContext], bool | CheckResult], name: str = "custom") -> Check:
    def wrapped(ctx: CheckContext) -> CheckResult:
        value = fn(ctx)
        if isinstance(value, CheckResult):
            return value
        return CheckResult(name, bool(value), "passed" if value else "failed")
    return Check(name, "custom", wrapped)


def from_spec(spec: dict) -> Check | None:
    """Build a check from the JSON a plan step carries."""
    if not isinstance(spec, dict):
        return None
    kind = str(spec.get("type") or spec.get("kind") or "").strip()
    if kind == "file_exists":
        return file_exists(str(spec.get("path") or ""), int(spec.get("min_bytes") or 1), bool(spec.get("fresh", False)))
    if kind == "stdout_matches":
        return stdout_matches(str(spec.get("pattern") or "."))
    if kind == "stdout_not_matches":
        return stdout_not_matches(str(spec.get("pattern") or "Traceback"))
    if kind == "exit_zero":
        return exit_zero()
    if kind == "csv_rows":
        return csv_rows(str(spec.get("path") or ""), int(spec.get("min_rows") or 1), spec.get("columns"))
    if kind == "json_valid":
        return json_valid(str(spec.get("path") or ""), spec.get("required_keys"))
    if kind == "command_exit_zero":
        return command_exit_zero(str(spec.get("command") or ""))
    if kind == "determinism":
        return determinism()
    return None


CHECK_KINDS = ("file_exists", "stdout_matches", "stdout_not_matches", "exit_zero", "csv_rows", "json_valid",
               "command_exit_zero", "determinism")


def run_checks(checks: list[Check], ctx: CheckContext) -> list[CheckResult]:
    return [check.run(ctx) for check in checks]
