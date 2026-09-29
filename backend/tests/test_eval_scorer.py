"""The eval scorer's unit tests, at its own boundary (spec's Testing Decisions).

The scorer is pure: an ``EvalQuestion`` plus a rag ``Answer`` in, one
deterministic ``EvalVerdict`` out. No provider, store, or harness code is
exercised here.
"""
import pytest

from app.eval_scorer import EvalQuestion, EvalVerdict, parse_eval_question, score_answer, summarize
from app.rag import Answer, Citation


def cited(*pages: int) -> tuple[Citation, ...]:
    """Citations whose only distinguishing field is the page."""
    return tuple(
        Citation(source="eu-ai-act.pdf", page=page, chunk_index=i, text="", score=0.9)
        for i, page in enumerate(pages)
    )


def answer(text: str, pages: tuple[int, ...] = (51,), refused: bool = False) -> Answer:
    return Answer(question="q", text=text, citations=cited(*pages), refused=refused)


def _score(
    *,
    keywords: tuple[str, ...] = (),
    expected_pages: tuple[int, ...] = (),
    cited_pages: tuple[int, ...] = (51,),
    text: str = "",
    expects_refusal: bool = False,
    refused: bool = False,
) -> "EvalVerdict":
    """Score one answer built from the given pieces against its question."""
    question = EvalQuestion(
        id="q1",
        question="q",
        expects_refusal=expects_refusal,
        keywords=keywords,
        pages=expected_pages,
    )
    rag_answer = Answer(
        question="q", text=text, citations=cited(*cited_pages), refused=refused
    )
    return score_answer(question, rag_answer)


def score(keywords: tuple[str, ...], expected_pages: tuple[int, ...], text: str) -> bool:
    """The common case: retrieval found the right pages, keywords decide."""
    return _score(
        keywords=keywords, expected_pages=expected_pages, cited_pages=expected_pages, text=text
    ).passed


def test_all_expected_keywords_in_answer_passes() -> None:
    assert score(("social scoring", "prohibited"), (51,), "Social scoring of natural persons is prohibited under Article 5.")


def test_missing_keyword_fails_and_is_reported() -> None:
    verdict = _score(keywords=("social scoring", "penalties"), expected_pages=(51,), text="Social scoring of natural persons is prohibited.")
    assert not verdict.passed
    assert verdict.missing_keywords == ("penalties",)


def test_keyword_matching_ignores_punctuation_and_case() -> None:
    # Corpus writes "EUR 35 000 000"; a model may reformat it — same tokens.
    assert score(("35 000 000", "7 % of"), (115,), "Fines reach EUR 35,000,000 or 7% of worldwide turnover.")


def test_no_citation_page_matching_expected_pages_fails() -> None:
    # Right keywords, but the citation points at the wrong page.
    verdict = _score(keywords=("social scoring",), expected_pages=(57,), cited_pages=(51,), text="Social scoring is prohibited.")
    assert not verdict.page_match
    assert not verdict.passed
    assert verdict.cited_pages == (51,)


def test_any_citation_page_among_expected_pages_matches() -> None:
    # Retrieval may hand back the recital chunk as well as the article chunk.
    assert score(("social scoring",), (9, 51), "Social scoring is prohibited.")


def test_empty_citations_cannot_match_pages() -> None:
    verdict = _score(keywords=("social scoring",), expected_pages=(51,), cited_pages=(), text="Social scoring is prohibited.")
    assert not verdict.page_match
    assert not verdict.passed


def test_in_scope_question_answered_with_refusal_sentence_fails() -> None:
    # The model quoted the exact refusal sentence the Prompt demands.
    verdict = _score(
        keywords=("social scoring",),
        expected_pages=(51,),
        text="I couldn't find that in the documents.",
    )
    assert verdict.refused
    assert not verdict.passed


def test_in_scope_question_refused_before_generation_fails() -> None:
    # Empty retrieval: refused=True, no citations at all.
    verdict = _score(
        keywords=("social scoring",), expected_pages=(51,), cited_pages=(), refused=True
    )
    assert verdict.refused
    assert not verdict.passed


def test_out_of_scope_question_correctly_refused_passes() -> None:
    verdict = _score(expects_refusal=True, text="I couldn't find that in the documents.")
    assert verdict.refused
    assert verdict.passed


def test_out_of_scope_question_refused_before_generation_passes() -> None:
    verdict = _score(expects_refusal=True, cited_pages=(), refused=True)
    assert verdict.refused
    assert verdict.passed


def test_out_of_scope_question_answered_instead_of_refused_fails() -> None:
    verdict = _score(expects_refusal=True, text="The AI Act covers prohibited practices such as social scoring.")
    assert not verdict.refused
    assert not verdict.passed
    assert "social scoring" in verdict.answer_text  # verbatim, for the owner's review


def test_summary_reports_pass_rates_per_scope() -> None:
    question = EvalQuestion(id="q1", question="q", expects_refusal=False, keywords=("k",), pages=(51,))
    oos_question = EvalQuestion(id="q2", question="q", expects_refusal=True)
    verdicts = [
        score_answer(question, answer("has k", (51,))),          # in-scope pass
        score_answer(question, answer("lacks it", (51,))),       # in-scope fail: keyword
        score_answer(question, answer("I couldn't find that in the documents.", (51,))),  # in-scope fail: refusal
        score_answer(oos_question, answer("I couldn't find that in the documents.", (51,))),  # out pass
        score_answer(oos_question, answer("made up answer", (51,))),  # out fail
    ]
    summary = summarize(verdicts)
    assert summary.total == 5
    assert summary.in_scope_total == 3
    assert summary.in_scope_passed == 1
    assert summary.out_of_scope_total == 2
    assert summary.out_of_scope_refused == 1


def test_parse_eval_question_from_json_entry() -> None:
    question = parse_eval_question(
        {"id": "prohibited", "question": "What is prohibited?", "expects_refusal": False,
         "keywords": ["social scoring"], "pages": [51]}
    )
    assert question.id == "prohibited"
    assert question.expects_refusal is False
    assert question.keywords == ("social scoring",)
    assert question.pages == (51,)


def test_parse_out_of_scope_question_requires_no_expectations() -> None:
    question = parse_eval_question(
        {"id": "capital", "question": "What is the capital of France?", "expects_refusal": True,
         "keywords": [], "pages": []}
    )
    assert question.expects_refusal is True


def test_parse_out_of_scope_question_with_keywords_is_rejected() -> None:
    # An out-of-scope Question has nothing to match — keywords there mean a
    # malformed entry, and the owner reviews the Set, not a silently ignored field.
    with pytest.raises(ValueError, match="out-of-scope"):
        parse_eval_question(
            {"id": "capital", "question": "Capital of France?", "expects_refusal": True,
             "keywords": ["paris"], "pages": []}
        )


def test_parse_missing_fields_is_a_clean_error() -> None:
    with pytest.raises(ValueError, match="id"):
        parse_eval_question({"question": "q", "expects_refusal": False, "keywords": [], "pages": []})