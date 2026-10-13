# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
The deterministic half of the repair loop.

* ``classify_failure`` - package / sandbox / timeout / system / script /
  logic, from the real output, by regex. The model is asked only for the
  residue (design §11.2).
* ``error_signature`` - the comparable identity of a failure. The same
  signature coming back unchanged means the diagnosis did not move.
* ``StoppingRule`` - when to stop repairing. Two rules, both deterministic:
  the fixed-point rule (unchanged failure ``repeat_limit`` times; DAYA's
  ``REPEAT_LIMIT``) and a Beta-Bernoulli rule: with prior Beta(a, b) on
  "the next attempt succeeds", updated by the attempts so far, stop when the
  posterior mean falls below the cost ratio ``cost_attempt / gain_success``.
  The prior is uncalibrated and flagged as such; until the evaluation suite
  sets it, the fixed-point rule is the one that fires in practice.
* ``extract_code`` / ``is_fragment`` - fenced-block extraction and the
  fragment rejection Patch Code applies (a reply much shorter than the file
  it replaces is a partial answer, not a repair).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .tools.install import missing_module_from

_FENCE_RE = re.compile(r"```(?:[a-zA-Z0-9+#.-]+)?[ \t]*\r?\n(.*?)```", re.DOTALL)
_TRACE_LAST_RE = re.compile(r"^(?P<etype>[A-Za-z_][\w.]*(?:Error|Exception|Warning|Exit|Interrupt))(?::\s*(?P<emsg>.*))?$", re.M)
_SYNTAX_RE = re.compile(r"SyntaxError|IndentationError|TabError|unexpected token|Parse error|syntax error", re.I)
_SANDBOX_RE = re.compile(r"iTailor sandbox:|DAYA sandbox:", re.I)
_NOT_YOUR_CODE_RE = re.compile(r"requested by an installed library", re.I)
_TIMEOUT_RE = re.compile(r"timed out after \d+s", re.I)
_SYSTEM_RE = re.compile(r"(command not found|is not recognized as an internal|No such file or directory: '(?:Rscript|node|java|gcc|go|cargo)|"
                        r"Permission denied|cannot execute binary|not found on PATH|CUDA|libgomp|GLIBC|MemoryError|Killed)", re.I)
_FILE_RE = re.compile(r"(FileNotFoundError|No such file or directory|ENOENT|cannot open file)", re.I)

KINDS = ("package", "sandbox", "timeout", "system", "file", "syntax", "script", "logic", "none")


@dataclass
class Failure:
    kind: str
    etype: str = ""
    emsg: str = ""
    module: str = ""
    manager: str = ""
    signature: str = ""
    repairable: bool = True
    note: str = ""
    missing_path: str = ""

    def to_dict(self) -> dict:
        return {"kind": self.kind, "etype": self.etype, "emsg": self.emsg[:300], "module": self.module,
                "manager": self.manager, "signature": self.signature, "repairable": self.repairable,
                "note": self.note, "missingPath": self.missing_path}


def _last_exception(text: str) -> tuple[str, str]:
    etype, emsg = "", ""
    for match in _TRACE_LAST_RE.finditer(text or ""):
        etype, emsg = match.group("etype"), (match.group("emsg") or "").strip()
    return etype, emsg


def error_signature(etype: str, emsg: str, kind: str = "") -> str:
    """A comparable string: exception type and message with numbers, paths and
    addresses normalised, so 'line 12' and 'line 13' do not look like progress."""
    msg = re.sub(r"0x[0-9a-fA-F]+", "0x?", str(emsg or ""))
    msg = re.sub(r"\d+", "#", msg)
    msg = re.sub(r"[A-Za-z]:\\[^\s'\"]+|/[^\s'\"]+", "<path>", msg)
    return f"{kind}|{etype}|{msg.strip()[:160]}".lower()


def classify_failure(stdout: str, stderr: str, exit_code: int | None, *, error: str = "") -> Failure:
    """Decide what went wrong from the real output. ``exit_code`` 0 → kind 'none'."""
    if exit_code == 0 and not error:
        return Failure(kind="none", signature="none")
    blame = "\n".join(s for s in (stderr, stdout, error) if s)
    etype, emsg = _last_exception(blame)
    missing = missing_module_from(blame)
    if missing:
        return Failure(kind="package", etype=etype or "ModuleNotFoundError", emsg=missing["line"],
                       module=missing["module"], manager=missing["manager"],
                       signature=error_signature("ModuleNotFoundError", missing["module"], "package"))
    if _SANDBOX_RE.search(blame):
        repairable = not _NOT_YOUR_CODE_RE.search(blame)
        return Failure(kind="sandbox", etype="PermissionError", emsg=emsg or blame[-300:],
                       repairable=repairable,
                       note="" if repairable else "an installed library asked for a path outside the sandbox; not fixable in code",
                       signature=error_signature("PermissionError", emsg, "sandbox"))
    if _TIMEOUT_RE.search(blame) or (error and "timed out" in error.lower()):
        return Failure(kind="timeout", etype="Timeout", emsg=error or "timed out",
                       signature=error_signature("Timeout", "", "timeout"))
    if _SYSTEM_RE.search(blame) and not _FILE_RE.search(blame):
        return Failure(kind="system", etype=etype or "SystemError", emsg=emsg or blame[-300:],
                       signature=error_signature(etype or "SystemError", emsg, "system"))
    if _SYNTAX_RE.search(blame):
        return Failure(kind="syntax", etype=etype or "SyntaxError", emsg=emsg,
                       signature=error_signature(etype or "SyntaxError", emsg, "syntax"))
    if _FILE_RE.search(blame):
        match = re.search(r"No such file or directory: '([^']+)'", blame)
        return Failure(kind="file", etype=etype or "FileNotFoundError", emsg=emsg,
                       missing_path=match.group(1) if match else "",
                       signature=error_signature(etype or "FileNotFoundError", emsg, "file"))
    if etype:
        return Failure(kind="script", etype=etype, emsg=emsg, signature=error_signature(etype, emsg, "script"))
    return Failure(kind="logic", etype="", emsg=(stderr or error or stdout or "")[-300:].strip(),
                   signature=error_signature("exit", str(exit_code), "logic"))


@dataclass
class StoppingRule:
    """Stop when the diagnosis stops moving, or when the posterior says more
    attempts are not worth their cost.

    ``prior_a``/``prior_b``: Beta prior on P(next attempt succeeds). Provenance:
    Beta(2, 1) means "two successes in three" - the author's rough reading of
    DAYA's repair logs, uncalibrated; the suite in evals/ should set it.
    ``cost_ratio``: cost of one more attempt divided by the value of a success;
    provenance: default 0.2, uncalibrated.
    """
    max_attempts: int = 6
    repeat_limit: int = 2
    prior_a: float = 2.0
    prior_b: float = 1.0
    cost_ratio: float = 0.2
    history: list = field(default_factory=list)   # signatures of failed attempts

    def record(self, signature: str) -> None:
        self.history.append(signature)

    @property
    def attempts(self) -> int:
        return len(self.history)

    def repeats_of_last(self) -> int:
        if not self.history:
            return 0
        last = self.history[-1]
        count = 0
        for sig in reversed(self.history):
            if sig != last:
                break
            count += 1
        return count

    def posterior_mean(self) -> float:
        failures = self.attempts
        return (self.prior_a) / (self.prior_a + self.prior_b + failures)

    def should_stop(self) -> tuple[bool, str]:
        if self.attempts >= self.max_attempts:
            return True, f"attempt budget of {self.max_attempts} spent"
        if self.repeats_of_last() >= self.repeat_limit:
            return True, f"the same failure came back unchanged {self.repeat_limit} times (fixed point)"
        mean = self.posterior_mean()
        if mean < self.cost_ratio:
            return True, (f"posterior success probability {mean:.2f} below the cost ratio {self.cost_ratio} "
                          f"(Beta({self.prior_a},{self.prior_b}) prior, {self.attempts} failures; prior uncalibrated)")
        return False, ""

    def escalate(self) -> bool:
        """True when the first repeat has happened: widen the repair scope."""
        return self.repeats_of_last() >= 1 and self.attempts >= 2


def extract_code(text: str, fence: str = "") -> str:
    """The script in a fenced block; the whole reply when there is no fence."""
    s = str(text or "")
    if fence:
        specific = re.search(r"```" + re.escape(fence) + r"[ \t]*\r?\n(.*?)```", s, re.DOTALL | re.IGNORECASE)
        if specific:
            return specific.group(1).strip()
    match = _FENCE_RE.search(s)
    if match:
        return match.group(1).strip()
    return s.strip().strip("`").strip()


def is_fragment(new_code: str, old_code: str, ratio: float = 0.5) -> bool:
    """A reply much shorter than the code it replaces is a partial answer.
    Provenance: Patch Code's fragment rejection (0.5 of the line count)."""
    old_lines = len([l for l in str(old_code or "").split("\n") if l.strip()])
    new_lines = len([l for l in str(new_code or "").split("\n") if l.strip()])
    return old_lines >= 8 and new_lines < old_lines * ratio
