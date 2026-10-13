# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
Risk scoring for an action: likelihood × impact on 1-5 scales, after the
semi-quantitative assessment in NIST SP 800-30 Rev. 1 (Appendix I, Table I-2
style), with the impact factors of an FMEA-like decomposition (IEC 60812):
reversibility, blast radius, data sensitivity, cost. The factor values are
deterministic functions of the action; no model is involved.

Score = likelihood × max(impact factors), range 1..25. Levels:

    very_low  ≤ 2 · low ≤ 5 · moderate ≤ 10 · high ≤ 16 · very_high > 16

Provenance of the factor tables and thresholds: author judgement,
2026-10-12, uncalibrated. They are the first thing the evaluation suite's
labelled policy set (design §11.4) should calibrate: false allows push the
thresholds down, unjustified interrupts push them up.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict

from .decisions import Action

# Likelihood that an action of this class causes harm when it goes wrong.
LIKELIHOOD = {"read": 1, "human": 1, "edit": 2, "install": 2, "network": 2,
              "run": 3, "shell": 3, "system": 3, "plan": 1, "step": 1, "budget": 2,
              "consult": 1, "lesson": 1, "write": 3, "exec_app": 3, "model": 1}

# Reversibility: 1 = trivially undone … 5 = cannot be undone.
REVERSIBILITY = {"read": 1, "human": 1, "edit": 3, "install": 3, "network": 4,
                 "run": 3, "shell": 3, "system": 3, "plan": 1, "step": 1, "budget": 1,
                 "consult": 1, "lesson": 2, "write": 3, "exec_app": 3, "model": 1}

_DELETE_RE = re.compile(r"(^|\s)(rm|rmdir|del|erase|Remove-Item|rd)\b|\bgit\s+(clean|reset\s+--hard|push\s+.*--force)|\b(drop\s+table|truncate)\b",
                        re.IGNORECASE)
_SENSITIVE_RE = re.compile(r"(\.env\b|credential|secret|password|id_rsa|id_ed25519|\.pem\b|\.key\b|\.kdbx\b|\btoken\b)",
                           re.IGNORECASE)
_SYSTEM_PATH_RE = re.compile(r"^(/(etc|usr|bin|sbin|boot|sys|proc|dev|var/lib)|[A-Za-z]:[\\/](Windows|Program Files))",
                             re.IGNORECASE)
_EGRESS_RE = re.compile(r"\b(curl|wget|scp|rsync|ssh|sftp|ftp|git\s+push|aws\s+s3\s+(cp|sync)|gsutil|az\s+storage|smtp|sendmail|mail)\b",
                        re.IGNORECASE)

LEVELS = ((2, "very_low"), (5, "low"), (10, "moderate"), (16, "high"), (25, "very_high"))


@dataclass
class RiskAssessment:
    likelihood: int
    impact: int
    score: int
    level: str
    factors: dict
    notes: list

    def to_dict(self) -> dict:
        return asdict(self)


def _blast_radius(action: Action, project_root: str = "") -> tuple[int, str]:
    paths = [str(p) for p in (action.paths or []) if p]
    if not paths:
        text = f"{action.command} {action.subject}"
        if _SYSTEM_PATH_RE.search(text):
            return 5, "names a system path"
        return (3, "command in the project") if action.klass in ("shell", "run", "system") else (1, "no path")
    worst, why = 1, "inside the run directory"
    for path in paths:
        if _SYSTEM_PATH_RE.search(path):
            return 5, f"system path {path}"
        if project_root:
            try:
                rel = os.path.relpath(os.path.abspath(path), os.path.abspath(project_root))
            except ValueError:
                rel = ".."
            if rel.startswith(".."):
                worst, why = max(worst, 4), f"outside the project: {path}"
            else:
                worst, why = max(worst, 2), "inside the project"
        else:
            worst, why = max(worst, 2), "project unknown"
    return worst, why


def assess(action: Action, project_root: str = "") -> RiskAssessment:
    notes: list = []
    klass = action.klass or "shell"
    likelihood = LIKELIHOOD.get(klass, 3)
    reversibility = REVERSIBILITY.get(klass, 3)
    text = f"{action.command} {action.subject} {action.detail}"
    if action.reversible is False or _DELETE_RE.search(text):
        reversibility = 5
        notes.append("deletes or discards data")
    elif action.reversible is True:
        reversibility = 1
    if action.read_only:
        likelihood, reversibility = 1, 1
    if action.destructive:
        likelihood, reversibility = 5, 5
        notes.append("matches the destructive hard-block list")
    radius, why = _blast_radius(action, project_root)
    notes.append(why)
    sensitivity = 1
    if _SENSITIVE_RE.search(" ".join([*map(str, action.paths or []), action.subject, action.command])):
        sensitivity = 5
        notes.append("touches credentials or secrets")
    egress = 1
    if action.egress or klass == "network" or _EGRESS_RE.search(text):
        egress = 4
        notes.append("sends data off the machine")
    cost = 1 if not action.cost else min(5, 1 + int(action.cost))
    factors = {"reversibility": reversibility, "blastRadius": radius, "dataSensitivity": sensitivity,
               "egress": egress, "cost": cost}
    impact = max(factors.values())
    score = likelihood * impact
    level = next(name for limit, name in LEVELS if score <= limit)
    return RiskAssessment(likelihood=likelihood, impact=impact, score=score, level=level,
                          factors=factors, notes=notes)
