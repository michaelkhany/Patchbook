# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
When to interrupt a human - the mixed-initiative decision rule.

Horvitz (1999): act autonomously when the expected cost of acting under
uncertainty is below the cost of the interruption, otherwise ask. The
expected cost is P(wrong) × cost(wrong). Whether a question is worth asking
at all is the value of information (Howard 1966): the expected gain from
learning the answer before acting - zero when every answer leads to the same
action, which is the case the rule exists to catch.

The agent uses ``consult_verdict`` with proxies for the probabilities it
cannot measure: the planner's materiality label for an unknown, the risk
level for an action. The proxies are listed with their provenance.
"""

from __future__ import annotations

# Costs on one scale (arbitrary units; only ratios matter).
# Provenance: author defaults, uncalibrated. An interruption costs about as much
# as a low-impact wrong action; a high-impact wrong action costs twenty times that.
COST_INTERRUPT = 1.0
COST_WRONG = {"low": 1.0, "moderate": 4.0, "high": 12.0, "very_high": 20.0}

# P(wrong) proxies from the planner's materiality label for an unknown.
# Provenance: author defaults, uncalibrated.
P_WRONG = {"low": 0.1, "medium": 0.35, "high": 0.6}

# The five triggers a model may cite when it proposes a consultation (design §2.5).
TRIGGERS = ("ambiguous_goal", "irreversible_or_outward", "evidence_contradicts",
            "cost_or_risk_fork", "lesson_says_ask")


def expected_cost_of_acting(p_wrong: float, cost_wrong: float) -> float:
    return max(0.0, p_wrong) * max(0.0, cost_wrong)


def should_interrupt(p_wrong: float, cost_wrong: float, cost_interrupt: float = COST_INTERRUPT) -> bool:
    """Horvitz's rule: interrupt when acting blind costs more than asking."""
    return expected_cost_of_acting(p_wrong, cost_wrong) > cost_interrupt


def value_of_information(state_probabilities: list[float], utilities: list[list[float]]) -> float:
    """Expected value of perfect information.

    ``utilities[a][s]`` is the utility of action ``a`` in state ``s``.
    EVPI = Σ_s p(s)·max_a u(a,s) − max_a Σ_s p(s)·u(a,s). Zero means no answer
    would change the best action, so there is nothing to ask.
    """
    if not utilities or not state_probabilities:
        return 0.0
    n_states = len(state_probabilities)
    total = sum(state_probabilities) or 1.0
    probs = [p / total for p in state_probabilities]
    with_info = sum(probs[s] * max(row[s] for row in utilities) for s in range(n_states))
    without = max(sum(probs[s] * row[s] for s in range(n_states)) for row in utilities)
    return max(0.0, with_info - without)


def consult_verdict(trigger: str, materiality: str = "medium", risk_level: str = "moderate",
                    options: list | None = None) -> dict:
    """Decide whether a proposed consultation meets the rule.

    Returns ``{"ask": bool, "reason": str, "expectedCost": float}``.
    An option list of length one has zero value of information and is refused.
    """
    trigger = str(trigger or "").strip()
    if trigger not in TRIGGERS:
        return {"ask": False, "reason": f"'{trigger}' is not one of the consultation triggers {TRIGGERS}",
                "expectedCost": 0.0}
    if options is not None and len(options) == 1:
        return {"ask": False, "reason": "only one option: no information to gain (EVPI = 0)", "expectedCost": 0.0}
    if trigger in ("irreversible_or_outward", "lesson_says_ask"):
        # These are not about uncertainty but about consent; the rule defers to the gate.
        return {"ask": True, "reason": f"trigger '{trigger}' requires consent", "expectedCost": float("inf")}
    p_wrong = P_WRONG.get(str(materiality).lower(), P_WRONG["medium"])
    cost_wrong = COST_WRONG.get(str(risk_level).lower(), COST_WRONG["moderate"])
    expected = expected_cost_of_acting(p_wrong, cost_wrong)
    ask = should_interrupt(p_wrong, cost_wrong)
    return {"ask": ask, "expectedCost": round(expected, 3),
            "reason": (f"expected cost of acting {expected:.2f} {'>' if ask else '<='} "
                       f"interruption cost {COST_INTERRUPT:.2f} (p_wrong={p_wrong}, cost_wrong={cost_wrong})")}
