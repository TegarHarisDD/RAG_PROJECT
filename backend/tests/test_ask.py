"""API seam: the POST /ask contract (ticket 06).

The FastAPI app runs against injected fakes — a store factory, ``embed_fn``,
``generate_fn``, and a fresh limiter — so the full HTTP contract (SSE event
shape, Citations payload, Refusal, abuse limits, error mapping) is verified
with no network (spec's Testing Decisions).
"""
import json
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.main import app
from app.abuse import AbuseLimiter
from app.ingest import IngestError
from app.providers import EmbeddingError, GenerationError
from tests.conftest import (
    TEST_PROVIDER_CONFIG,
    TEST_RETRIEVAL,
    FakeStore,
    fake_generate,
    hit,
)


def fake_embed(texts: Sequence[str], *, config: object) -> list[list[float]]:
    return [[0.1] for _ in texts]


def sse_events(body: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse a full SSE body into (event, data) pairs."""
    events: list[tuple[str, dict[str, Any]]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        name: str | None = None
        data: dict[str, Any] = {}
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        assert name is not None, f"SSE block without an event name: {block!r}"
        events.append((name, data))
    return events


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """A client with the happy-path fakes installed; tests retarget the
    dependency overrides directly for failure and abuse-limit scenarios."""
    app.dependency_overrides[main.get_store_factory] = lambda: (lambda: FakeStore(
        [hit(0, "obligations text"), hit(1, "more text")]
    ))
    app.dependency_overrides[main.get_provider_config] = lambda: TEST_PROVIDER_CONFIG
    app.dependency_overrides[main.get_retrieval_config] = lambda: TEST_RETRIEVAL
    app.dependency_overrides[main.get_embed_fn] = lambda: fake_embed
    app.dependency_overrides[main.get_generate_fn] = lambda: fake_generate([["The ", "answer"]])
    # Created once: the dependency override runs per request, and a fresh
    # limiter per request would remember nothing.
    limiter = AbuseLimiter(per_ip_per_hour=5, daily_limit=40)
    app.dependency_overrides[main.get_limiter] = lambda: limiter
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def ask(client: TestClient, question: str = "Which obligations apply to providers?"):
    return client.post("/ask", json={"text": question})


class TestStreamingContract:
    def test_streams_tokens_then_a_citations_payload(self, client: TestClient) -> None:
        """The stream is SSE: token events in order, ending with a Citations
        payload carrying Document, page, and verbatim Chunk text."""
        response = ask(client)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = sse_events(response.text)
        assert [name for name, _ in events] == ["token", "token", "citations"]
        assert [data["text"] for name, data in events if name == "token"] == ["The ", "answer"]
        (citations_event,) = [data for name, data in events if name == "citations"]
        assert citations_event["citations"] == [
            {
                "source": "eu-ai-act.pdf",
                "page": 12,
                "chunk_index": 0,
                "text": "obligations text",
                "score": 0.9,
            },
            {
                "source": "eu-ai-act.pdf",
                "page": 13,
                "chunk_index": 1,
                "text": "more text",
                "score": 0.8,
            },
        ]

    def test_streams_with_configured_top_k(self, client: TestClient) -> None:
        """The endpoint retrieves with the configured top-k, not a hardcoded one."""
        store = FakeStore([hit(0, "text")])
        app.dependency_overrides[main.get_store_factory] = lambda: (lambda: store)

        ask(client)

        assert store.searched_k == TEST_RETRIEVAL.top_k

    def test_refusal_streams_as_a_distinct_event(self, client: TestClient) -> None:
        """Nothing retrieved: a refusal event the UI can render distinctly —
        no token events, no citations payload, and no LLM call spent."""
        app.dependency_overrides[main.get_store_factory] = lambda: (lambda: FakeStore())
        generate_fn = fake_generate([["should never be reached"]])
        app.dependency_overrides[main.get_generate_fn] = lambda: generate_fn

        response = ask(client, "What is the capital of France?")

        assert response.status_code == 200
        assert sse_events(response.text) == [
            ("refusal", {"message": "I couldn't find that in the documents."})
        ]


class TestAbuseLimits:
    def test_questions_over_the_length_cap_are_rejected(self, client: TestClient) -> None:
        """A 501-character Question fails validation with an explicit 422."""
        response = ask(client, "x" * 501)

        assert response.status_code == 422

    def test_blank_questions_are_rejected(self, client: TestClient) -> None:
        """A whitespace-only Question would spend real provider quota on
        nothing — rejected with the same explicit 422."""
        response = ask(client, "   ")

        assert response.status_code == 422

    def test_sixth_question_in_an_hour_from_one_ip_is_rejected(
        self, client: TestClient
    ) -> None:
        """The per-IP limit is an explicit, distinguishable 429 — not a 500 —
        and the rejected question is not answered."""
        for _ in range(5):
            assert ask(client).status_code == 200

        response = ask(client)

        assert response.status_code == 429
        body = response.json()
        assert body["error"] == "rate_limit"
        assert "message" in body

    def test_global_daily_stop_is_a_distinct_rejection(self, client: TestClient) -> None:
        """Once the day's global quota is spent, even a first-time visitor gets
        the daily-stop rejection — the honest 'come back tomorrow'."""
        limiter = AbuseLimiter(per_ip_per_hour=5, daily_limit=2)
        app.dependency_overrides[main.get_limiter] = lambda: limiter
        app.dependency_overrides[main.get_store_factory] = lambda: (lambda: FakeStore())

        assert ask(client).status_code == 200
        assert ask(client).status_code == 200

        response = ask(client)
        assert response.status_code == 429
        assert response.json()["error"] == "daily_limit"


class TestErrorMapping:
    def test_exhausted_fallback_chain_streams_a_clean_error_event(
        self, client: TestClient
    ) -> None:
        """All models failing is an SSE error event with a readable message —
        never a 500 or a stack trace."""
        def failing_generate(prompt: str, **kwargs: object) -> Iterator[str]:
            raise GenerationError("All fallback models failed: llm-a:free: HTTP 429")
            yield  # pragma: no cover - makes this a generator like the real one

        app.dependency_overrides[main.get_generate_fn] = lambda: failing_generate

        response = ask(client)

        assert response.status_code == 200  # the stream started; the failure is in-band
        assert sse_events(response.text) == [
            ("error", {"kind": "generation", "message": "All fallback models failed: llm-a:free: HTTP 429"})
        ]

    def test_embed_failures_stream_a_provider_error_event(self, client: TestClient) -> None:
        """OpenRouter being down surfaces as a clean provider error event."""
        def failing_embed(texts: Sequence[str], *, config: object) -> list[list[float]]:
            raise EmbeddingError("Embedding request failed: ConnectError")

        app.dependency_overrides[main.get_embed_fn] = lambda: failing_embed

        response = ask(client)

        assert sse_events(response.text) == [
            ("error", {"kind": "provider", "message": "Embedding request failed: ConnectError"})
        ]

    def test_mongodb_failures_stream_a_store_error_event(self, client: TestClient) -> None:
        """Atlas being unreachable is a clean store error event — the store
        factory raises inside the stream, never as a dependency-time 500."""
        def broken_factory() -> FakeStore:
            raise IngestError("Could not reach the Atlas cluster: ServerSelectionTimeoutError")

        app.dependency_overrides[main.get_store_factory] = lambda: broken_factory

        response = ask(client)

        assert sse_events(response.text) == [
            ("error", {"kind": "store",
                       "message": "Could not reach the Atlas cluster: ServerSelectionTimeoutError"})
        ]

    def test_unexpected_bugs_still_get_a_terminal_error_event(self, client: TestClient) -> None:
        """An exception outside the mapped families (a malformed store hit, a
        code bug) must not drop the SSE connection silently — a terminal
        ``internal`` error event ends the stream instead."""
        def broken_search(vector: Sequence[float], k: int) -> list[dict[str, object]]:
            raise KeyError("source")  # a malformed hit, as if the store were corrupt

        store = FakeStore()
        store.search = broken_search  # type: ignore[method-assign]
        app.dependency_overrides[main.get_store_factory] = lambda: (lambda: store)

        response = ask(client)

        (event,) = sse_events(response.text)
        name, data = event
        assert name == "error"
        assert data["kind"] == "internal"
        assert "source" in data["message"]