"""The Eval Set's own data contract: shape, counts, and page bounds.

This tests the data file, not the harness — the harness is a script outside
the test suite (spec's Testing Decisions). Every entry must parse through the
scorer's ``parse_eval_question`` so the harness can never run on malformed
data, and the owner's review starts from a file that keeps its promises.
"""
import json
from pathlib import Path
from typing import Any, cast

from app.eval_scorer import _tokens, parse_eval_question

EVAL_SET_PATH = Path(__file__).resolve().parents[1] / "evals" / "eval_set.json"

# The spec's shape: ~50 Questions, ≈40 in-scope, 10 out-of-scope.
IN_SCOPE = 40
OUT_SCOPE = 10

# Body pages of the ingested Corpus (annexes stripped): 1..123 of the PDF.
MAX_CORPUS_PAGE = 123


def load_entries() -> list[dict[str, object]]:
    data = json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
    assert isinstance(data["description"], str) and data["description"]
    return data["questions"]


def test_eval_set_parses_and_has_the_spec_shape() -> None:
    entries = load_entries()
    assert len(entries) == IN_SCOPE + OUT_SCOPE
    questions = [parse_eval_question(entry) for entry in entries]
    assert sum(1 for q in questions if q.expects_refusal) == OUT_SCOPE
    assert sum(1 for q in questions if not q.expects_refusal) == IN_SCOPE


def test_eval_question_ids_are_unique() -> None:
    entries = load_entries()
    ids = [str(entry["id"]) for entry in entries]
    assert len(ids) == len(set(ids))


def test_in_scope_pages_stay_inside_the_corpus() -> None:
    # A page beyond the body would silently never match a Citation.
    for entry in load_entries():
        if entry["expects_refusal"]:
            continue
        for page in cast("list[int]", entry["pages"]):
            assert 1 <= int(page) <= MAX_CORPUS_PAGE, entry["id"]


def test_every_in_scope_question_has_distinctive_keywords() -> None:
    # Single generic tokens ("risk", "ai") would pass on almost any answer,
    # which makes the scorer rubber-stamp instead of measuring.
    generic = {"ai", "act", "regulation", "risk", "system", "systems"}
    for entry in load_entries():
        if entry["expects_refusal"]:
            continue
        keywords = cast("list[Any]", entry["keywords"])
        assert len(keywords) >= 1, entry["id"]
        for keyword in keywords:
            # The scorer's own tokenizer: "machine-based" -> machine, based.
            tokens = _tokens(str(keyword).lower())
            assert any(token not in generic for token in tokens), (entry["id"], keyword)
