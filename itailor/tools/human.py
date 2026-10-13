# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
The AskUser tool: the agent's own request for a human decision (a
consultation, not a permission). The request must cite one of the five
triggers; the mixed-initiative rule (``policy.interrupt``) decides whether
the question is worth the interruption. An answer is recorded as a lesson.
"""

from __future__ import annotations

from ..oversight import ConsultRequest
from ..policy.interrupt import TRIGGERS, consult_verdict
from .registry import ToolContext


def ask_user(args: dict, ctx: ToolContext) -> dict:
    question = str(args.get("question") or "").strip()
    if not question:
        return {"error": "question is required."}
    options = [str(o) for o in (args.get("options") or []) if str(o).strip()]
    trigger = str(args.get("trigger") or "").strip()
    materiality = str(args.get("materiality") or "medium").lower()
    verdict = consult_verdict(trigger, materiality=materiality, options=options or None)
    if not verdict["ask"]:
        return {"answered": False, "declined": True,
                "error": f"This question does not meet the consultation rule ({verdict['reason']}). "
                         f"Make the routine decision yourself, state the assumption in your final answer, "
                         f"and only ask when one of {TRIGGERS} genuinely applies."}
    ctx.say("consult_request", question, options=options, why=args.get("why", ""), trigger=trigger,
            materiality=materiality, rule=verdict["reason"])
    if ctx.oversight is None:
        return {"answered": False, "answer": None,
                "note": "Nobody is available to answer. Proceed with the most conservative assumption and say so."}
    request = ConsultRequest(question=question, options=options, why=str(args.get("why") or ""),
                             trigger=trigger, context=str(ctx.step.get("title") or ""))
    timeout = float((ctx.settings or {}).get("consultTimeoutSeconds") or 600)
    answer = ctx.oversight.consult(request, timeout=timeout, cancel=ctx.cancel)
    ctx.say("consult_answer", answer or "(no answer)", requestId=request.id, answered=answer is not None)
    if answer is None:
        return {"answered": False, "answer": None,
                "note": "No answer arrived. Proceed with the most conservative assumption, state it, and continue."}
    if ctx.lessons is not None:
        try:
            lesson = ctx.lessons.record_consult(
                {"question": question[:200], "trigger": trigger, "options": options,
                 "goal_tags": list(ctx.step.get("tags") or []), "step": str(ctx.step.get("title") or "")},
                answer, rationale=str(args.get("why") or ""))
            ctx.say("lesson", f"remembered: {answer[:80]}", lessonId=lesson.id, kind="consult")
        except Exception:  # noqa: BLE001
            pass
    return {"answered": True, "answer": answer}
