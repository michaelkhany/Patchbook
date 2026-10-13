# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
itailor.policy - a dependency-free, deterministic policy and decision engine.

Gates, deciders, rules, a risk scorer and the mixed-initiative interrupt
rule. Imports nothing from the rest of iTailor (design §9).
"""

from .decisions import (ABSTAIN, ALLOW, ALLOW_WITH, ASK, DEFER, DENY, GATES, MODES, TOOL_CLASS,
                        VERDICTS, Action, Context, Decision, Trace, subject_of)
from .rules import first_match, glob_to_regex, parse_rule, rule_matches
from .risk import RiskAssessment, assess
from .interrupt import (TRIGGERS, consult_verdict, should_interrupt, value_of_information,
                        expected_cost_of_acting)
from .engine import (HARD_BLOCK, PROFILES, Decider, HardBlockDecider, LessonsDecider, ModeDecider,
                     OrgPolicyDecider, PlanPreapprovalDecider, PolicyEngine, RiskDecider, RulesDecider,
                     default_chain, is_destructive, load_entry_point_deciders)

__all__ = [
    "ABSTAIN", "ALLOW", "ALLOW_WITH", "ASK", "DEFER", "DENY", "GATES", "MODES", "TOOL_CLASS", "VERDICTS",
    "Action", "Context", "Decision", "Trace", "subject_of",
    "first_match", "glob_to_regex", "parse_rule", "rule_matches",
    "RiskAssessment", "assess",
    "TRIGGERS", "consult_verdict", "should_interrupt", "value_of_information", "expected_cost_of_acting",
    "HARD_BLOCK", "PROFILES", "Decider", "HardBlockDecider", "LessonsDecider", "ModeDecider",
    "OrgPolicyDecider", "PlanPreapprovalDecider", "PolicyEngine", "RiskDecider", "RulesDecider",
    "default_chain", "is_destructive", "load_entry_point_deciders",
]
