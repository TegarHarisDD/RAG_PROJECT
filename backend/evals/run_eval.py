"""Eval harness: run the Eval Set against the live pipeline and emit a table.

A script, deliberately not part of the test suite (spec's Testing Decisions):
every Question costs two real provider calls (one embed, one generation), so
the free-tier daily cap (~50 requests, ADR-0001) cannot cover the full Set in
one day. Results are therefore cached per Question in ``evals/results.json``
and runs resume by default — completed Questions are skipped (unless the
Question's text or expectations changed, or ``--fresh``), errored ones are
retried on the next run.

Run from ``backend/``::

    python -m evals.run_eval                 # run/resume the whole Set
    python -m evals.run_eval --limit 5       # first 5 un-run Questions
    python -m evals.run_eval --only penalties-prohibited
    python -m evals.run_eval --fresh         # ignore cached results, redo all

Outputs: ``evals/results.json`` (raw, resumable) and ``evals/results.md``
(the results table for the README).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from app.atlas import AtlasChunkStore
from app.config import ProviderConfig, RetrievalConfig, load_provider_config, load_retrieval_config
from app.eval_scorer import (
    EvalQuestion,
    EvalVerdict,
    parse_eval_question,
    score_answer,
    summarize,
)
from app.ingest import IngestError
from app.providers import ProviderError
from app.rag import ask

EVAL_DIR = Path(__file__).resolve().parent
EVAL_SET_PATH = EVAL_DIR / "eval_set.json"
RESULTS_PATH = EVAL_DIR / "results.json"
RESULTS_MD_PATH = EVAL_DIR / "results.md"

_RETRY_PAUSE_SECONDS = 5.0


def load_questions() -> list[EvalQuestion]:
    """Parse every entry of the Eval Set; malformed data stops the run here."""
    data = json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
    return [parse_eval_question(entry) for entry in data["questions"]]


def question_fingerprint(question: EvalQuestion) -> str:
    """Hash of everything that changes a Question's expected result."""
    payload = json.dumps(
        {
            "id": question.id,
            "question": question.question,
            "expects_refusal": question.expects_refusal,
            "keywords": list(question.keywords),
            "pages": list(question.pages),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_cache() -> dict[str, dict[str, Any]]:
    if RESULTS_PATH.exists():
        return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    return {}


def run_one(
    question: EvalQuestion,
    *,
    store: AtlasChunkStore,
    config: ProviderConfig,
    retrieval: RetrievalConfig,
    attempts: int,
) -> tuple[EvalVerdict | None, str | None]:
    """One Question through the live pipeline, with retries for transient
    network failures. Returns ``(verdict, None)`` or ``(None, error)``."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            answer = ask(
                question.question, config=config, retrieval=retrieval, store=store
            )
            return score_answer(question, answer), None
        except (ProviderError, IngestError) as exc:
            last_error = exc
            if attempt < attempts:
                print(f"  {question.id}: {exc} (retry {attempt}/{attempts - 1})")
                time.sleep(_RETRY_PAUSE_SECONDS)
    return None, f"{last_error.__class__.__name__}: {last_error}"


def fresh_verdicts(
    questions: list[EvalQuestion], cache: dict[str, dict[str, Any]]
) -> list[EvalVerdict]:
    """Verdicts scored against the current Question text/expectations — a
    record whose fingerprint is stale counts as not run, both here and in the
    table."""
    return [
        EvalVerdict.from_record(record["verdict"])
        for question in questions
        if (record := cache.get(question.id)) is not None
        and record.get("status") == "ok"
        and record.get("input_hash") == question_fingerprint(question)
    ]


def _expected_pages_cell(question: EvalQuestion) -> str:
    """The Expected pages table cell: what a scored row must hit."""
    return (
        "refusal" if question.expects_refusal else ", ".join(map(str, question.pages))
    )


def render_markdown(
    questions: list[EvalQuestion], cache: dict[str, dict[str, Any]]
) -> str:
    """The results table: a summary block plus one row per Question."""
    verdicts = fresh_verdicts(questions, cache)
    summary = summarize(verdicts)
    error_count = sum(
        1
        for question in questions
        if cache.get(question.id, {}).get("status") == "error"
        and cache[question.id].get("input_hash") == question_fingerprint(question)
    )
    lines = [
        "# Eval results",
        "",
        f"- In-scope: **{summary.in_scope_passed}/{summary.in_scope_total} passed** "
        "(expected keywords present, a citation page matches, no Refusal)",
        f"- Out-of-scope: **{summary.out_of_scope_refused}/{summary.out_of_scope_total} "
        "correctly refused**",
        f"- Not scored: {len(questions) - len(verdicts) - error_count} not yet run, "
        f"{error_count} errored (rerun the harness to retry them)",
        "",
        "| Question | Scope | Verdict | Missing keywords | Cited pages | Expected pages |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for i, question in enumerate(questions, start=1):
        record = cache.get(question.id)
        scope = "out" if question.expects_refusal else "in"
        if record is None or record.get("input_hash") != question_fingerprint(question):
            lines.append(f"| {i}. {question.id} | {scope} | not run | — | — | "
                         f"{_expected_pages_cell(question)} |")
            continue
        if record["status"] == "error":
            lines.append(
                f"| {i}. {question.id} | {scope} | ERROR | {record['error']} | — | "
                f"{_expected_pages_cell(question)} |"
            )
            continue
        v = record["verdict"]
        verdict_label = "PASS" if v["passed"] else "FAIL"
        missing = ", ".join(v["missing_keywords"]) or "—"
        cited = ", ".join(map(str, v["cited_pages"])) or "—"
        lines.append(
            f"| {i}. {question.id} | {scope} | {verdict_label} | {missing} | {cited} | "
            f"{_expected_pages_cell(question)} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_eval", description="Run the Eval Set against the live pipeline."
    )
    parser.add_argument("--limit", type=int, metavar="N", help="run at most N Questions this session")
    parser.add_argument("--only", metavar="ID", help="run one Question by id (ignores --limit)")
    parser.add_argument("--fresh", action="store_true", help="ignore cached results and redo everything")
    parser.add_argument("--attempts", type=int, default=2, help="retries per Question for transient network errors")
    args = parser.parse_args(argv)

    questions = load_questions()
    if args.only:
        questions = [q for q in questions if q.id == args.only]
        if not questions:
            print(f"error: no Eval Question with id {args.only!r}", file=sys.stderr)
            return 1
    budget = args.limit if args.limit is not None else len(questions)

    cache = {} if args.fresh else load_cache()
    config = load_provider_config()
    retrieval = load_retrieval_config()
    store = AtlasChunkStore.from_env()

    run_count = 0
    passed_count = 0
    for question in questions:
        fingerprint = question_fingerprint(question)
        cached = cache.get(question.id)
        if cached is not None and cached.get("status") == "ok" and cached.get("input_hash") == fingerprint:
            continue  # already answered against the same Question text
        if run_count >= budget:
            break

        verdict, error = run_one(
            question, store=store, config=config, retrieval=retrieval, attempts=args.attempts
        )
        run_count += 1
        if error is not None:
            cache[question.id] = {"input_hash": fingerprint, "status": "error", "error": error}
            print(f"{question.id}: ERROR {error}")
            continue
        assert verdict is not None
        cache[question.id] = {
            "input_hash": fingerprint,
            "status": "ok",
            "verdict": verdict.to_record(),
        }
        passed_count += 1 if verdict.passed else 0
        marker = "PASS" if verdict.passed else "FAIL"
        detail = ""
        if verdict.expects_refusal and not verdict.refused:
            detail = f" (answered: {verdict.answer_text[:80]!r})"
        elif verdict.missing_keywords:
            detail = f" (missing: {', '.join(verdict.missing_keywords)})"
        elif not verdict.page_match and not verdict.expects_refusal:
            detail = f" (cited pages {list(verdict.cited_pages)}, expected {list(question.pages)})"
        print(f"{question.id}: {marker}{detail}")

        RESULTS_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")

    # Persist even when everything was cached or the last Question errored.
    RESULTS_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown = render_markdown(load_questions(), cache)
    RESULTS_MD_PATH.write_text(markdown, encoding="utf-8")

    summary = summarize(fresh_verdicts(load_questions(), cache))
    print(
        f"\nDone: ran {run_count} this session ({passed_count} passed). "
        f"Overall: {summary.in_scope_passed}/{summary.in_scope_total} in-scope passed, "
        f"{summary.out_of_scope_refused}/{summary.out_of_scope_total} out-of-scope refused."
    )
    print(f"Results: {RESULTS_PATH}\nTable:   {RESULTS_MD_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
