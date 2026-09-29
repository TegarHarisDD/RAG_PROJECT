"""The deterministic eval scorer: an Eval Question + a rag Answer -> a verdict.

Pure functions only — no network, no store, no files — so the boundary is
unit-tested directly (see the spec's Testing Decisions) and the same scoring
is reproducible on every run. The eval harness script (``evals/run_eval.py``)
drives it against the live pipeline; nothing else uses it.

Scoring rules, all deterministic:
- keyword match: every expected keyword appears in the answer text, compared
  as lowercase alphanumeric token sequences (punctuation, spacing, and digit
  formatting like ``35,000,000`` vs ``35 000 000`` do not matter)
- citation page match: at least one Citation's page is among the expected pages
- Refusal correctness: out-of-scope Questions must produce a Refusal (the
  programmatic one or the model quoting ``REFUSAL_MESSAGE``); an in-scope
  Question answered with a Refusal is a miss — the owner reviews those
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
from dataclasses import dataclass

from app.rag import REFUSAL_MESSAGE, Answer

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    """Lowercase alphanumeric tokens — the normalization both sides go through."""
    return _TOKEN.findall(text.lower())


def _contains(haystack: list[str], needle: list[str]) -> bool:
    """True when ``needle`` is a contiguous token subsequence of ``haystack``."""
    if not needle:
        return False
    return any(
        haystack[i : i + len(needle)] == needle
        for i in range(len(haystack) - len(needle) + 1)
    )


@dataclass(frozen=True)
class EvalQuestion:
    """One Eval Question with its expected outcome (CONTEXT.md: Eval Question)."""

    id: str
    question: str
    expects_refusal: bool  # out-of-scope: the correct answer is a Refusal
    keywords: tuple[str, ...] = ()
    pages: tuple[int, ...] = ()


def parse_eval_question(entry: Mapping[str, object]) -> EvalQuestion:
    """Parse one Eval Set JSON entry, rejecting malformed data with a clean
    ``ValueError`` naming the field — the harness and the Set's own validation
    test both go through this, so bad data fails loudly before any live run."""
    for field in ("id", "question", "expects_refusal", "keywords", "pages"):
        if field not in entry:
            raise ValueError(f"Eval Question is missing the field {field!r}")
    keywords = tuple(entry["keywords"])  # type: ignore[arg-type, var-annotated]
    pages = tuple(entry["pages"])  # type: ignore[arg-type, var-annotated]
    expects_refusal = bool(entry["expects_refusal"])
    if expects_refusal and (keywords or pages):
        raise ValueError(
            f"out-of-scope Eval Question {entry['id']!r} must expect a Refusal "
            "with no keywords or pages"
        )
    if not expects_refusal and (not keywords or not pages):
        raise ValueError(
            f"in-scope Eval Question {entry['id']!r} needs both expected "
            "keywords and expected pages"
        )
    return EvalQuestion(
        id=str(entry["id"]),
        question=str(entry["question"]),
        expects_refusal=expects_refusal,
        keywords=tuple(str(kw) for kw in keywords),
        pages=tuple(int(page) for page in pages),
    )


@dataclass(frozen=True)
class EvalVerdict:
    """What scoring one Question produced, with the evidence for the owner."""

    question_id: str
    expects_refusal: bool  # out-of-scope: the correct answer was a Refusal
    passed: bool
    refused: bool  # a Refusal was detected in the answer
    missing_keywords: tuple[str, ...]  # expected keywords absent from the answer
    page_match: bool  # at least one citation page among the expected pages
    cited_pages: tuple[int, ...]
    answer_text: str  # verbatim, for the owner's review of misses

    def to_record(self) -> dict[str, Any]:
        """The JSON-safe slice the harness caches in results.json."""
        return {
            "question_id": self.question_id,
            "expects_refusal": self.expects_refusal,
            "passed": self.passed,
            "refused": self.refused,
            "missing_keywords": list(self.missing_keywords),
            "page_match": self.page_match,
            "cited_pages": list(self.cited_pages),
            "answer_text": self.answer_text,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> EvalVerdict:
        """Rebuild a verdict from its ``to_record`` JSON slice."""
        return cls(
            question_id=record["question_id"],
            expects_refusal=record["expects_refusal"],
            passed=record["passed"],
            refused=record["refused"],
            missing_keywords=tuple(record["missing_keywords"]),
            page_match=record["page_match"],
            cited_pages=tuple(record["cited_pages"]),
            answer_text=record["answer_text"],
        )


@dataclass(frozen=True)
class EvalSummary:
    """The aggregate the README results table reports."""

    total: int
    in_scope_total: int
    in_scope_passed: int
    out_of_scope_total: int
    out_of_scope_refused: int


def summarize(verdicts: Sequence[EvalVerdict]) -> EvalSummary:
    """Aggregate per-Question verdicts into the per-scope pass counts."""
    in_scope = [v for v in verdicts if not v.expects_refusal]
    out_scope = [v for v in verdicts if v.expects_refusal]
    return EvalSummary(
        total=len(verdicts),
        in_scope_total=len(in_scope),
        in_scope_passed=sum(1 for v in in_scope if v.passed),
        out_of_scope_total=len(out_scope),
        out_of_scope_refused=sum(1 for v in out_scope if v.refused),
    )


def score_answer(question: EvalQuestion, answer: Answer) -> EvalVerdict:
    """Score one rag ``Answer`` against one ``EvalQuestion``, deterministically."""
    answer_tokens = _tokens(answer.text)
    refusal_tokens = _tokens(REFUSAL_MESSAGE)
    refused = answer.refused or _contains(answer_tokens, refusal_tokens)

    if question.expects_refusal:
        return EvalVerdict(
            question_id=question.id,
            expects_refusal=question.expects_refusal,
            passed=refused,
            refused=refused,
            missing_keywords=(),
            page_match=False,
            cited_pages=tuple(c.page for c in answer.citations),
            answer_text=answer.text,
        )

    missing = tuple(kw for kw in question.keywords if not _contains(answer_tokens, _tokens(kw)))
    cited_pages = tuple(c.page for c in answer.citations)
    page_match = bool(set(cited_pages) & set(question.pages))
    passed = not refused and not missing and page_match
    return EvalVerdict(
        question_id=question.id,
        expects_refusal=question.expects_refusal,
        passed=passed,
        refused=refused,
        missing_keywords=missing,
        page_match=page_match,
        cited_pages=cited_pages,
        answer_text=answer.text,
    )