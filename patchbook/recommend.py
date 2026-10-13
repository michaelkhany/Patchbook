# Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
A recommendation for every permission question, from what iTailor already knows.

iTailor's policy engine scores every consequential action (likelihood x impact,
with reversibility, blast radius, data sensitivity, egress and cost as factors)
and attaches the assessment to the question, together with hints from earlier
answers (its lessons). Patchbook turns that into one line a person can act on,
"Recommended: Allow once, low risk, reversible, inside the project", and, when
the user chose to let clear cases be answered for them, into the answer itself.
Nothing here names a program or a package; it reads the assessment.
"""

from __future__ import annotations

import re

ALLOW_HINT = re.compile(r"\b(allow|allowed|always|accepted|approved)\b", re.IGNORECASE)
DENY_HINT = re.compile(r"\b(deny|denied|declin|refus|rejected)\w*", re.IGNORECASE)
UNSURE_NOTE = re.compile(r"(off the machine|system path|outside the project|irreversible|delete|remove)", re.IGNORECASE)


def recommend(payload: dict) -> dict:
    """``{"decision": allow|deny|ask, "confident": bool, "label": ..., "reason": ...}`` for a permission request."""
    if payload.get("requestType") == "consult":
        return {"decision": "ask", "confident": False, "label": "Your call", "reason": "iTailor needs a decision only you can make."}
    risk = payload.get("risk") if isinstance(payload.get("risk"), dict) else {}
    level = str(risk.get("level") or "")
    score = risk.get("score")
    notes = [str(n) for n in (risk.get("notes") or [])]
    hints = [str(h) for h in (payload.get("hints") or [])]
    kind = str(payload.get("kind") or "")
    why: list[str] = []
    if level:
        why.append(f"{level.replace('_', ' ')} risk" + (f" (score {score})" if score is not None else ""))
    why.extend(notes[:3])
    earlier_allow = any(ALLOW_HINT.search(h) and not DENY_HINT.search(h) for h in hints)
    earlier_deny = any(DENY_HINT.search(h) for h in hints)
    unsure = any(UNSURE_NOTE.search(n) for n in notes)

    if kind == "plan":
        return {"decision": "allow", "confident": False, "label": "Review the plan", "reason": "A plan is best read once before it runs."}
    if level in ("very_low", "low"):
        decision, confident = "allow", True
    elif level == "moderate":
        decision, confident = "allow", not unsure
    elif level == "high":
        decision, confident = ("allow", False) if earlier_allow else ("deny", False)
    elif level == "very_high":
        decision, confident = "deny", True
    else:
        decision, confident = "ask", False
    if earlier_deny and decision == "allow":
        decision, confident = "deny", False
        why.append("you declined something like this before")
    elif earlier_allow and decision == "allow" and not confident and not unsure:
        confident = True
        why.append("you allowed this kind before")
    label = {"allow": "Allow once", "deny": "Don't allow", "ask": "Your call"}[decision]
    if decision == "deny" and not confident:
        label = "Don't allow, unless you expected this"
    return {"decision": decision, "confident": confident, "label": label, "reason": "; ".join(w for w in why if w) or "no assessment available"}


def standing_rule(payload: dict) -> str:
    """A standing allow rule for this kind of action, in the library's own rule form (``Tool(prefix:*)``)."""
    tool = str(payload.get("tool") or "").strip()
    subject = str(payload.get("command") or payload.get("summary") or "").strip()
    if not tool:
        return ""
    return f"{tool}({subject.split(' ')[0]}:*)" if subject else tool
