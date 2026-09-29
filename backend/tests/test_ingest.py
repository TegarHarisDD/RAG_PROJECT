"""Ingestion: batched embedding, ADR-0002 document shape, orchestrator decisions.

All behavior is tested through injected fakes — a recording ``embed_fn`` and an
in-memory ``ChunkStore`` — so no test touches OpenRouter or Atlas for real
(per the spec's Testing Decisions). The pymongo glue in ``app.atlas`` is
verified against the live cluster, not here. The one subprocess test exercises
the real CLI error boundary without any network at all.
"""
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest

from app.chunker import Chunk
from app.config import ProviderConfig
from app.ingest import (
    IngestMeta,
    chunk_documents,
    embed_chunks,
    ingest_chunks,
    needs_reset,
    probe,
    vector_index_definition,
)


class MemoryStore:
    """An in-memory ChunkStore stand-in recording every mutating call."""

    def __init__(self, meta: IngestMeta | None = None, count: int = 0) -> None:
        self.stored_meta = meta
        self.stored_count = count
        self.docs: list[Mapping[str, object]] = []
        self.index_definition: Mapping[str, object] | None = None
        self.reset_called = False
        self.replace_calls = 0
        self.search_results: list[dict[str, object]] = []
        self.searched_vector: list[float] | None = None
        self.searched_k: int | None = None

    def state(self) -> tuple[IngestMeta | None, int]:
        return self.stored_meta, self.stored_count

    def reset(self) -> None:
        self.reset_called = True
        self.stored_meta = None
        self.stored_count = 0

    def replace_documents(self, docs: Sequence[Mapping[str, object]]) -> None:
        self.docs = list(docs)
        self.replace_calls += 1
        first = docs[0] if docs else None
        self.stored_meta = IngestMeta(
            str(first["embedding_model"]) if first else "none",
            cast(int, first["dim"]) if first else 0,
        )
        self.stored_count = len(docs)

    def ensure_index(self, definition: Mapping[str, object]) -> None:
        self.index_definition = definition

    def search(self, vector: Sequence[float], k: int) -> list[dict[str, object]]:
        self.searched_vector = list(vector)
        self.searched_k = k
        return self.search_results


def test_ingest_chunks_populates_empty_store_with_index() -> None:
    """Empty store: embed everything, store docs, ensure the index; no reset."""
    chunks = [fake_chunk(i, f"text {i}") for i in range(3)]
    embed_fn = recording_embed([[[0.1], [0.2]], [[0.3]]])
    store = MemoryStore()

    report = ingest_chunks(
        chunks, config=TEST_CONFIG, store=store, batch_size=2, embed_fn=embed_fn
    )

    assert store.reset_called is False
    assert store.replace_calls == 1
    assert [d["chunk_index"] for d in store.docs] == [0, 1, 2]
    assert store.docs[0]["embedding_model"] == "test-embedder:free"
    assert store.docs[0]["dim"] == 1
    assert store.index_definition == vector_index_definition(1)
    assert report.action == "ingested"
    assert report.source == "corpus.pdf"
    assert (report.chunks, report.model, report.dim) == (3, "test-embedder:free", 1)


def test_ingest_chunks_resets_store_when_embedding_model_changes() -> None:
    """Model change: store reset happens only after embedding succeeded, then re-store."""
    chunks = [fake_chunk(i, f"text {i}") for i in range(2)]
    embed_fn = recording_embed([[[9.9], [8.8]]])
    store = MemoryStore(meta=IngestMeta("old-embedder:free", 768), count=5)

    report = ingest_chunks(
        chunks, config=TEST_CONFIG, store=store, batch_size=10, embed_fn=embed_fn
    )

    assert store.reset_called is True
    assert [d["embedding_model"] for d in store.docs] == ["test-embedder:free", "test-embedder:free"]
    assert store.docs[0]["dim"] == 1
    assert store.index_definition == vector_index_definition(1)
    assert report.action == "reset+ingested"


def test_ingest_chunks_resets_when_dim_changes_under_same_model() -> None:
    """Same model name but a different vector dim is still an incompatible mix."""
    chunks = [fake_chunk(0, "text 0")]
    embed_fn = recording_embed([[[0.1] * 512]])
    store = MemoryStore(meta=IngestMeta("test-embedder:free", 1024), count=2)

    report = ingest_chunks(chunks, config=TEST_CONFIG, store=store, embed_fn=embed_fn)

    assert store.reset_called is True
    assert report.action == "reset+ingested"


def test_ingest_chunks_skips_reembedding_unchanged_corpus() -> None:
    """Same model, probe-confirmed dim, matching chunk count: only one probe
    embed happens, nothing is rewritten, and the index is still ensured —
    a prior run that failed during index creation gets repaired here."""
    chunks = [fake_chunk(i, f"text {i}") for i in range(3)]
    embed_fn = recording_embed([[[0.5] * 1024]])  # the dim probe
    store = MemoryStore(meta=IngestMeta("test-embedder:free", 1024), count=3)

    report = ingest_chunks(
        chunks, config=TEST_CONFIG, store=store, embed_fn=embed_fn
    )

    assert embed_fn.calls == [["text 0"]]  # the probe only — no re-embed
    assert store.reset_called is False
    assert store.replace_calls == 0
    assert store.index_definition == vector_index_definition(1024)
    assert report.action == "skipped"
    assert report.chunks == 3


def test_ingest_chunks_resets_when_dim_drifts_under_unchanged_corpus() -> None:
    """Same model ID and chunk count but the probe reveals a different dim:
    drop-and-recreate — never a silent mix of incompatible vectors (ADR-0002)."""
    chunks = [fake_chunk(i, f"text {i}") for i in range(2)]
    embed_fn = recording_embed(
        [[[0.1] * 512], [[0.2] * 512, [0.3] * 512]]  # probe, then re-embed both
    )
    store = MemoryStore(meta=IngestMeta("test-embedder:free", 1024), count=2)

    report = ingest_chunks(chunks, config=TEST_CONFIG, store=store, embed_fn=embed_fn)

    assert store.reset_called is True
    assert store.replace_calls == 1
    assert report.action == "reset+ingested"


def test_ingest_chunks_rejects_zero_vectors_cleanly() -> None:
    """A 200 with an empty vectors list is a clean IngestError, not an IndexError."""
    with pytest.raises(Exception, match="no vectors"):
        ingest_chunks(
            [fake_chunk(0, "text")], config=TEST_CONFIG, store=MemoryStore(),
            embed_fn=recording_embed([[]]),
        )


def test_probe_rejects_bad_vector_count_cleanly() -> None:
    """A probe response without exactly one vector is a clean IngestError."""
    with pytest.raises(Exception, match="one question"):
        probe("q", config=TEST_CONFIG, store=MemoryStore(),
              embed_fn=recording_embed([[], []]))


def test_ingest_chunks_force_reembeds_unchanged_corpus() -> None:
    """--force re-embeds and re-stores even when the stored corpus looks current."""
    chunks = [fake_chunk(i, f"text {i}") for i in range(2)]
    embed_fn = recording_embed([[[0.5], [0.6]]])
    store = MemoryStore(meta=IngestMeta("test-embedder:free", 1), count=2)

    report = ingest_chunks(
        chunks, config=TEST_CONFIG, store=store, embed_fn=embed_fn, force=True
    )

    assert store.reset_called is False  # same meta: index stays, docs replaced
    assert store.replace_calls == 1
    assert [d["embedding"] for d in store.docs] == [[0.5], [0.6]]
    assert report.action == "ingested"


def test_ingest_chunks_rejects_empty_corpus() -> None:
    """A Corpus that produces no Chunks is a clean error, not an empty store."""
    embed_fn = recording_embed([])
    with pytest.raises(Exception, match="No Chunks"):
        ingest_chunks([], config=TEST_CONFIG, store=MemoryStore(), embed_fn=embed_fn)


def test_probe_embeds_the_question_and_searches_the_store() -> None:
    """--check: the Question is embedded once, then searched against the index."""
    store = MemoryStore()
    store.search_results = [{"text": "relevant chunk", "score": 0.91}]
    embed_fn = recording_embed([[[0.7, 0.8]]])

    hits = probe("What is the AI Act?", config=TEST_CONFIG, store=store,
                 embed_fn=embed_fn, k=4)

    assert embed_fn.calls == [["What is the AI Act?"]]
    assert store.searched_vector == [0.7, 0.8]
    assert store.searched_k == 4
    assert hits == [{"text": "relevant chunk", "score": 0.91}]


def test_cli_maps_store_errors_to_clean_messages_no_traceback() -> None:
    """``python -m app.ingest`` loads this file as ``__main__`` while app.atlas
    imports ``app.ingest`` — two module objects. The CLI must catch the
    canonical ``app.ingest.IngestError`` atlas raises, not its own ``__main__``
    copy, or stack traces leak past the clean-error boundary. A bad URI scheme
    fails fast inside pymongo with no network touched.
    """
    env = {**os.environ, "MONGODB_URI": "nope://x"}
    proc = subprocess.run(
        [sys.executable, "-m", "app.ingest", "--check", "x"],
        capture_output=True,
        text=True,
        env=env,
        cwd=Path(__file__).resolve().parents[1],
        timeout=60,
    )
    assert proc.returncode == 1
    assert "error: Could not connect to Atlas: InvalidURI" in proc.stderr
    assert "Traceback" not in proc.stderr


TEST_CONFIG = ProviderConfig(
    openrouter_api_key="test-key",
    openrouter_base_url="https://openrouter.ai/api/v1",
    embedding_model="test-embedder:free",
    llm_models=("llm-a:free",),
)


def fake_chunk(index: int, text: str) -> Chunk:
    return Chunk(text=text, source="corpus.pdf", page=1 + index // 2, chunk_index=index)


def recording_embed(vectors_by_call: list[list[list[float]]]):
    """An embed_fn stand-in that returns pre-set vectors per call and records inputs."""
    calls: list[list[str]] = []

    def embed_fn(texts, *, config):
        calls.append(list(texts))
        return vectors_by_call[len(calls) - 1]

    embed_fn.calls = calls  # type: ignore[attr-defined]
    return embed_fn


def test_embed_chunks_splits_into_batches_and_preserves_order() -> None:
    """Chunks are embedded in batch-size slices; vectors come back in chunk order."""
    chunks = [fake_chunk(i, f"text {i}") for i in range(5)]
    embed_fn = recording_embed([
        [[0.1], [0.2]],  # chunks 0-1
        [[0.3], [0.4]],  # chunks 2-3
        [[0.5]],         # chunk 4
    ])

    vectors = embed_chunks(chunks, config=TEST_CONFIG, batch_size=2, embed_fn=embed_fn)

    assert vectors == [[0.1], [0.2], [0.3], [0.4], [0.5]]
    assert embed_fn.calls == [["text 0", "text 1"], ["text 2", "text 3"], ["text 4"]]


def test_chunk_documents_carries_full_metadata_per_adr_0002() -> None:
    """Every Chunk stores text, embedding, source, page, chunk_index, model, dim."""
    chunks = [fake_chunk(0, "hello world"), fake_chunk(1, "second span")]
    meta = IngestMeta(embedding_model="test-embedder:free", dim=1024)

    docs = chunk_documents(chunks, [[0.1] * 1024, [0.2] * 1024], meta)

    assert docs == [
        {
            "text": "hello world",
            "embedding": [0.1] * 1024,
            "source": "corpus.pdf",
            "page": 1,
            "chunk_index": 0,
            "embedding_model": "test-embedder:free",
            "dim": 1024,
        },
        {
            "text": "second span",
            "embedding": [0.2] * 1024,
            "source": "corpus.pdf",
            "page": 1,
            "chunk_index": 1,
            "embedding_model": "test-embedder:free",
            "dim": 1024,
        },
    ]


def test_chunk_documents_rejects_vector_count_mismatch() -> None:
    """Fewer vectors than Chunks is an ingestion-time failure, not silent corruption."""
    with pytest.raises(Exception, match="vector"):
        chunk_documents([fake_chunk(0, "a"), fake_chunk(1, "b")], [[0.1]], IngestMeta("m", 1))


def test_needs_reset_on_model_or_dim_change_only() -> None:
    """A model or dim change drops everything; a same-config re-run keeps the store."""
    stored = IngestMeta(embedding_model="test-embedder:free", dim=1024)

    assert not needs_reset(stored, IngestMeta("test-embedder:free", 1024))
    assert needs_reset(stored, IngestMeta("other-embedder:free", 1024))
    assert needs_reset(stored, IngestMeta("test-embedder:free", 768))


def test_vector_index_definition_is_one_cosine_field_on_embedding_path() -> None:
    """Exactly one vector field (free-tier limit is 3 indexes) bound to the dim."""
    definition = vector_index_definition(1024)

    assert definition == {
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": 1024,
                "similarity": "cosine",
            }
        ]
    }