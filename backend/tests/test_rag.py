"""Retrieval + answer pipeline: Question -> top-k Chunks -> Prompt -> streamed answer.

Everything runs against fakes — a recording store, ``embed_fn``, and
``generate_fn`` — so orchestration, Prompt assembly, and Refusal behavior are
verified with no network (spec's Testing Decisions). One subprocess test pins
the CLI error boundary without touching Atlas or OpenRouter.
"""
import os
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest

from app.config import ProviderConfig, RetrievalConfig
from app.ingest import IngestMeta, IngestError
from app.providers import GenerationError
from app.rag import (
    REFUSAL_MESSAGE,
    Answer,
    Citation,
    FinalEvent,
    TokenEvent,
    ask,
    ask_stream,
    build_prompt,
    retrieve,
)

TEST_CONFIG = ProviderConfig(
    openrouter_api_key="test-key",
    openrouter_base_url="https://openrouter.ai/api/v1",
    embedding_model="test-embedder:free",
    llm_models=("llm-a:free",),
)
TEST_RETRIEVAL = RetrievalConfig(top_k=4, temperature=0.2)


class FakeStore:
    """A ChunkStore stand-in: preset search hits, recording the search call."""

    def __init__(self, hits: Sequence[dict[str, object]] | None = None) -> None:
        self.hits = list(hits or [])
        self.searched_vector: list[float] | None = None
        self.searched_k: int | None = None

    def state(self) -> tuple[IngestMeta | None, int]:
        return IngestMeta("test-embedder:free", 1024), 10

    def reset(self) -> None: ...

    def replace_documents(self, docs: Sequence[Mapping[str, object]]) -> None: ...

    def ensure_index(self, definition: Mapping[str, object]) -> None: ...

    def search(self, vector: Sequence[float], k: int) -> list[dict[str, object]]:
        self.searched_vector = list(vector)
        self.searched_k = k
        return list(self.hits)


def recording_embed(vectors_by_call: list[list[list[float]]]):
    """An embed_fn stand-in returning pre-set vectors per call, recording inputs."""
    calls: list[list[str]] = []

    def embed_fn(texts, *, config):
        calls.append(list(texts))
        return vectors_by_call[len(calls) - 1]

    embed_fn.calls = calls  # type: ignore[attr-defined]
    return embed_fn


def fake_generate(tokens_by_call: list[list[str]]):
    """A generate_fn stand-in yielding pre-set tokens, recording its arguments."""
    calls: list[dict[str, object]] = []

    def generate_fn(prompt, *, config, temperature=None, on_attempt=None):
        calls.append(
            {"prompt": prompt, "temperature": temperature, "config": config}
        )
        yield from tokens_by_call[len(calls) - 1]

    generate_fn.calls = calls  # type: ignore[attr-defined]
    return generate_fn


def hit(index: int, text: str) -> dict[str, object]:
    """A store hit in the shape AtlasChunkStore.search projects."""
    return {
        "text": text,
        "source": "eu-ai-act.pdf",
        "page": 12 + index,
        "chunk_index": index,
        "score": 0.9 - index / 10,
    }


def question_embed(vectors: list[list[float]]):
    return recording_embed([vectors])


class TestRetrieve:
    def test_embeds_the_question_and_searches_with_configured_top_k(self) -> None:
        """The Question is embedded once, then searched with k from config."""
        store = FakeStore([hit(0, "obligations text")])
        embed_fn = question_embed([[0.7, 0.8]])

        citations = retrieve(
            "Which obligations apply to providers?",
            config=TEST_CONFIG,
            retrieval=TEST_RETRIEVAL,
            store=store,
            embed_fn=embed_fn,
        )

        assert embed_fn.calls == [["Which obligations apply to providers?"]]
        assert store.searched_vector == [0.7, 0.8]
        assert store.searched_k == 4  # TEST_RETRIEVAL.top_k
        assert len(citations) == 1
        assert citations[0] == Citation(
            source="eu-ai-act.pdf", page=12, chunk_index=0,
            text="obligations text", score=0.9,
        )

    def test_hits_come_back_in_store_order(self) -> None:
        """Citation order is the store's similarity order — never re-sorted."""
        store = FakeStore([hit(0, "first"), hit(1, "second"), hit(2, "third")])

        citations = retrieve(
            "q", config=TEST_CONFIG, retrieval=TEST_RETRIEVAL,
            store=store, embed_fn=question_embed([[0.1]]),
        )

        assert [c.text for c in citations] == ["first", "second", "third"]

    def test_empty_hits_give_no_citations(self) -> None:
        """A search with no matches is an empty tuple, not an error."""
        citations = retrieve(
            "q", config=TEST_CONFIG, retrieval=TEST_RETRIEVAL,
            store=FakeStore(), embed_fn=question_embed([[0.1]]),
        )
        assert citations == ()

    def test_bad_vector_count_is_a_clean_error(self) -> None:
        """An embed response without exactly one vector is a clean error."""
        with pytest.raises(IngestError, match="one question"):
            retrieve(
                "q", config=TEST_CONFIG, retrieval=TEST_RETRIEVAL,
                store=FakeStore(), embed_fn=recording_embed([[], []]),
            )


class TestBuildPrompt:
    def test_contains_rules_question_and_verbatim_chunks(self) -> None:
        """System rules (answer-only, cite Document+page, Refuse) + Question + Chunks."""
        citations = (
            Citation("eu-ai-act.pdf", 12, 0, "verbatim obligations text", 0.9),
            Citation("eu-ai-act.pdf", 30, 1, "annex-adjacent span", 0.8),
        )

        prompt = build_prompt("What must providers of high-risk AI systems do?", citations)

        assert "What must providers of high-risk AI systems do?" in prompt
        assert "Answer ONLY from the excerpts" in prompt
        assert "Document and page" in prompt
        assert REFUSAL_MESSAGE in prompt
        assert "[1] eu-ai-act.pdf p.12" in prompt
        assert "verbatim obligations text" in prompt
        assert "[2] eu-ai-act.pdf p.30" in prompt
        assert "annex-adjacent span" in prompt

    def test_chunk_text_is_included_verbatim(self) -> None:
        """The Chunk text appears unmodified — the model can only cite what it sees."""
        text = "   odd   spacing and (special; characters) survive!  "
        prompt = build_prompt("q", (Citation("s.pdf", 1, 0, text, 0.9),))
        assert text in prompt


class TestAsk:
    def test_streams_tokens_and_returns_answer_with_citations(self) -> None:
        """Tokens flow to on_token in order; the Answer carries text + evidence."""
        store = FakeStore([hit(0, "obligations text"), hit(1, "more text")])
        embed_fn = question_embed([[0.7, 0.8]])
        generate_fn = fake_generate([["The ", "obligations ", "are..."]])
        streamed: list[str] = []

        answer = ask(
            "Which obligations apply to providers?",
            config=TEST_CONFIG,
            retrieval=TEST_RETRIEVAL,
            store=store,
            embed_fn=embed_fn,
            generate_fn=generate_fn,
            on_token=streamed.append,
        )

        assert streamed == ["The ", "obligations ", "are..."]
        assert answer == Answer(
            question="Which obligations apply to providers?",
            text="The obligations are...",
            citations=(
                Citation("eu-ai-act.pdf", 12, 0, "obligations text", 0.9),
                Citation("eu-ai-act.pdf", 13, 1, "more text", 0.8),
            ),
            refused=False,
        )

    def test_generate_receives_the_assembled_prompt_and_low_temperature(self) -> None:
        """The Prompt sent downstream contains the Question and Chunk text, at the
        configured low temperature — never a bare Question."""
        store = FakeStore([hit(0, "obligations text")])
        generate_fn = fake_generate([["ok"]])

        ask(
            "Which obligations apply?",
            config=TEST_CONFIG, retrieval=TEST_RETRIEVAL, store=store,
            embed_fn=question_embed([[0.1]]), generate_fn=generate_fn,
        )

        (call,) = cast(list[dict[str, object]], generate_fn.calls)
        prompt = cast(str, call["prompt"])
        assert call["temperature"] == 0.2
        assert "Which obligations apply?" in prompt
        assert "obligations text" in prompt

    def test_refuses_without_calling_the_llm_when_nothing_was_retrieved(self) -> None:
        """No matching Chunks: the honest Refusal, no LLM request spent on it."""
        generate_fn = fake_generate([["should never be reached"]])

        answer = ask(
            "What is the capital of France?",
            config=TEST_CONFIG, retrieval=TEST_RETRIEVAL,
            store=FakeStore(), embed_fn=question_embed([[0.1]]),
            generate_fn=generate_fn,
        )

        assert answer.refused is True
        assert answer.text == REFUSAL_MESSAGE
        assert answer.citations == ()
        assert generate_fn.calls == []  # the free daily cap is not spent

    def test_generation_failure_propagates_to_the_caller(self) -> None:
        """An exhausted fallback chain is not swallowed — callers handle it."""
        def failing_generate(prompt, *, config, temperature=None, on_attempt=None):
            raise GenerationError("All fallback models failed: llm-a:free: HTTP 429")
            yield  # pragma: no cover - makes this a generator like the real one

        with pytest.raises(GenerationError, match="All fallback models failed"):
            ask(
                "q", config=TEST_CONFIG, retrieval=TEST_RETRIEVAL,
                store=FakeStore([hit(0, "text")]),
                embed_fn=question_embed([[0.1]]),
                generate_fn=failing_generate,
            )


class TestAskStream:
    """The event-stream seam the /ask endpoint consumes (ticket 06)."""

    def test_yields_each_token_then_the_cited_answer(self) -> None:
        """Tokens arrive as they are generated; the final event carries the Answer."""
        store = FakeStore([hit(0, "obligations text")])
        generate_fn = fake_generate([["The ", "obligations ", "are..."]])

        events = list(ask_stream(
            "Which obligations apply?",
            config=TEST_CONFIG, retrieval=TEST_RETRIEVAL, store=store,
            embed_fn=question_embed([[0.1]]), generate_fn=generate_fn,
        ))

        assert events[:3] == [TokenEvent("The "), TokenEvent("obligations "), TokenEvent("are...")]
        (final,) = events[3:]
        assert final == FinalEvent(Answer(
            question="Which obligations apply?",
            text="The obligations are...",
            citations=(Citation("eu-ai-act.pdf", 12, 0, "obligations text", 0.9),),
            refused=False,
        ))

    def test_yields_a_refusal_event_without_tokens_when_nothing_was_retrieved(self) -> None:
        """The Refusal is one distinct final event — no token events precede it."""
        generate_fn = fake_generate([["should never be reached"]])

        events = list(ask_stream(
            "What is the capital of France?",
            config=TEST_CONFIG, retrieval=TEST_RETRIEVAL,
            store=FakeStore(), embed_fn=question_embed([[0.1]]),
            generate_fn=generate_fn,
        ))

        assert events == [FinalEvent(Answer(
            question="What is the capital of France?",
            text=REFUSAL_MESSAGE, citations=(), refused=True,
        ))]
        assert generate_fn.calls == []


def test_safe_print_replaces_characters_the_console_cannot_encode() -> None:
    """Windows consoles often run cp1252, which cannot map characters the models
    emit (e.g. the non-breaking hyphen U+2011) — stream printing would crash
    mid-answer. Unencodable characters are replaced instead."""
    import io

    from app import cli

    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")

    cli._safe_print("high‑risk obligations", stream=out)

    raw = out.buffer.getvalue().decode("cp1252")  # type: ignore[union-attr]
    assert "high" in raw and "obligations" in raw
    assert "‑" not in raw  # replaced, not fatal


def test_cli_ask_maps_store_errors_to_clean_messages_no_traceback() -> None:
    """``python -m app.cli ask`` with a broken MONGODB_URI fails cleanly: exit
    code 1, a readable stderr message, no traceback. A bad URI scheme fails
    fast inside pymongo with no network touched."""
    env = {**os.environ, "MONGODB_URI": "nope://x"}
    proc = subprocess.run(
        [sys.executable, "-m", "app.cli", "ask", "What is the AI Act?"],
        capture_output=True,
        text=True,
        env=env,
        cwd=Path(__file__).resolve().parents[1],
        timeout=60,
    )
    assert proc.returncode == 1
    assert "error: Could not connect to Atlas: InvalidURI" in proc.stderr
    assert "Traceback" not in proc.stderr