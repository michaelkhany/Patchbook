# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
Lessons: what a human decided, and what finally worked, remembered for next time.

Case-based reasoning (Aamodt & Plaza 1994): *retrieve* lessons whose
situation matches, *reuse* them as hints in the prompt and the permission
request, *revise* them with the outcome, *retain* the new case. Retrieval is
BM25 (Robertson & Zaragoza 2009; k1 = 1.2, b = 0.75, the standard defaults)
over the situation text plus Jaccard overlap on tags; confidence is a
Laplace-smoothed success rate (s + 1) / (n + 2).

Lessons inform; they never authorise. A permission lesson with ``always``
becomes a *proposed* rule that is written to settings only when the user
says yes (design §2.6). Storage is JSON lines a human can read and edit:
``<project>/.itailor/lessons.jsonl`` and ``~/.itailor/lessons.jsonl``.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import uuid
from dataclasses import dataclass, field, asdict

KINDS = ("permission", "consult", "repair", "preference")
_TOKEN_RE = re.compile(r"[a-z0-9_.+-]+")

# BM25 parameters (Robertson & Zaragoza 2009, §3.3 defaults).
BM25_K1 = 1.2
BM25_B = 0.75
# Final score mix. Provenance: author default, uncalibrated.
TEXT_WEIGHT, TAG_WEIGHT = 0.7, 0.3


@dataclass
class Lesson:
    kind: str
    situation: dict
    decision: str = ""
    rationale: str = ""
    fix: str = ""
    scope: str = "project"
    id: str = field(default_factory=lambda: f"L-{time.strftime('%Y-%m-%d')}-{uuid.uuid4().hex[:6]}")
    created: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    uses: int = 0
    successes: int = 0
    last_used: str = ""
    tags: list = field(default_factory=list)

    def text(self) -> str:
        parts = [self.kind, self.decision, self.rationale, self.fix]
        parts.extend(f"{k} {v}" for k, v in (self.situation or {}).items() if not isinstance(v, (list, dict)))
        parts.extend(" ".join(map(str, v)) for v in (self.situation or {}).values() if isinstance(v, list))
        return " ".join(str(p) for p in parts if p)

    @property
    def confidence(self) -> float:
        return (self.successes + 1) / (self.uses + 2)

    def to_dict(self) -> dict:
        return asdict(self)


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(str(text or "").lower())


def situation_text(situation: dict) -> str:
    parts = []
    for key, value in (situation or {}).items():
        if isinstance(value, list):
            parts.append(" ".join(map(str, value)))
        elif isinstance(value, dict):
            continue
        else:
            parts.append(f"{key} {value}")
    return " ".join(parts)


class LessonStore:
    def __init__(self, path: str, user_path: str | None = None) -> None:
        self.path = path
        self.user_path = user_path
        self._lessons: list[Lesson] | None = None

    # -- persistence ---------------------------------------------------------
    def _read(self, path: str) -> list[Lesson]:
        out: list[Lesson] = []
        if not path or not os.path.isfile(path):
            return out
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    known = {k: v for k, v in data.items() if k in Lesson.__dataclass_fields__}
                    out.append(Lesson(**known))
                except Exception:  # noqa: BLE001 - a bad line is skipped, not fatal
                    continue
        return out

    def _write(self, path: str, lessons: list[Lesson]) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            for lesson in lessons:
                handle.write(json.dumps(lesson.to_dict(), ensure_ascii=False) + "\n")

    def all(self) -> list[Lesson]:
        if self._lessons is None:
            self._lessons = self._read(self.path) + [l for l in self._read(self.user_path or "") if l.scope == "user"]
        return list(self._lessons)

    def add(self, lesson: Lesson) -> Lesson:
        lessons = self.all()
        lessons.append(lesson)
        self._lessons = lessons
        target = self.user_path if (lesson.scope == "user" and self.user_path) else self.path
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(lesson.to_dict(), ensure_ascii=False) + "\n")
        return lesson

    def forget(self, lesson_id: str) -> bool:
        lessons = self.all()
        kept = [l for l in lessons if l.id != lesson_id]
        if len(kept) == len(lessons):
            return False
        self._lessons = kept
        self._write(self.path, [l for l in kept if l.scope != "user" or not self.user_path])
        if self.user_path:
            self._write(self.user_path, [l for l in kept if l.scope == "user"])
        return True

    def mark_used(self, lesson_id: str, success: bool | None = None) -> None:
        for lesson in self.all():
            if lesson.id == lesson_id:
                lesson.uses += 1
                if success:
                    lesson.successes += 1
                lesson.last_used = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._write(self.path, [l for l in self.all() if l.scope != "user" or not self.user_path])
        if self.user_path:
            self._write(self.user_path, [l for l in self.all() if l.scope == "user"])

    # -- retrieval -----------------------------------------------------------
    def retrieve(self, situation: dict, *, kind: str | None = None, k: int = 5,
                 min_score: float = 0.15) -> list[tuple[Lesson, float]]:
        corpus = [l for l in self.all() if kind is None or l.kind == kind]
        if not corpus:
            return []
        query_tokens = tokenize(situation_text(situation))
        query_tags = {str(t).lower() for t in (situation.get("goal_tags") or situation.get("tags") or [])}
        docs = [tokenize(l.text()) for l in corpus]
        avg_len = sum(len(d) for d in docs) / max(1, len(docs))
        n = len(docs)
        df: dict[str, int] = {}
        for doc in docs:
            for term in set(doc):
                df[term] = df.get(term, 0) + 1
        scores = []
        for lesson, doc in zip(corpus, docs):
            tf: dict[str, int] = {}
            for term in doc:
                tf[term] = tf.get(term, 0) + 1
            bm25 = 0.0
            for term in query_tokens:
                if term not in tf:
                    continue
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                freq = tf[term]
                bm25 += idf * freq * (BM25_K1 + 1) / (freq + BM25_K1 * (1 - BM25_B + BM25_B * len(doc) / avg_len))
            lesson_tags = {str(t).lower() for t in lesson.tags} | {
                str(t).lower() for t in (lesson.situation.get("goal_tags") or [])}
            union = query_tags | lesson_tags
            jaccard = len(query_tags & lesson_tags) / len(union) if union else 0.0
            scores.append((lesson, bm25, jaccard))
        max_bm25 = max((s[1] for s in scores), default=0.0) or 1.0
        ranked = [(l, TEXT_WEIGHT * (b / max_bm25) + TAG_WEIGHT * j) for l, b, j in scores]
        ranked = [(l, s) for l, s in ranked if s >= min_score]
        ranked.sort(key=lambda pair: (-pair[1], -pair[0].confidence))
        return ranked[:k]

    # -- recording -----------------------------------------------------------
    def record_permission(self, situation: dict, decision: str, rationale: str = "",
                          scope: str = "project", tags: list | None = None) -> Lesson:
        return self.add(Lesson(kind="permission", situation=situation, decision=decision,
                               rationale=rationale, scope=scope, tags=list(tags or [])))

    def record_consult(self, situation: dict, answer: str, rationale: str = "",
                       scope: str = "project", tags: list | None = None) -> Lesson:
        return self.add(Lesson(kind="consult", situation=situation, decision=answer,
                               rationale=rationale, scope=scope, tags=list(tags or [])))

    def record_repair(self, situation: dict, fix: str, scope: str = "project",
                      tags: list | None = None) -> Lesson:
        return self.add(Lesson(kind="repair", situation=situation, fix=fix, decision="repaired",
                               scope=scope, tags=list(tags or [])))

    # -- rule proposals ------------------------------------------------------
    def propose_rules(self) -> list[dict]:
        """``always`` permission lessons, as candidate standing rules. The user decides."""
        proposals = []
        for lesson in self.all():
            if lesson.kind != "permission" or lesson.decision != "always":
                continue
            tool = lesson.situation.get("tool") or ""
            subject = lesson.situation.get("subject") or lesson.situation.get("command") or ""
            if not tool:
                continue
            rule = f"{tool}({subject.split(' ')[0]}:*)" if subject else tool
            proposals.append({"lessonId": lesson.id, "rule": rule, "list": "allow",
                              "rationale": lesson.rationale, "uses": lesson.uses})
        return proposals


def prompt_block(matches: list[tuple[Lesson, float]]) -> str:
    if not matches:
        return ""
    lines = ["LESSONS FROM EARLIER RUNS (they inform your choices; they do not authorise anything):"]
    for lesson, score in matches:
        what = lesson.fix or lesson.decision
        why = f" - {lesson.rationale}" if lesson.rationale else ""
        where = situation_text(lesson.situation)[:160]
        lines.append(f"- [{lesson.kind}, confidence {lesson.confidence:.2f}] in situation '{where}': {what}{why}")
    return "\n".join(lines) + "\n"
