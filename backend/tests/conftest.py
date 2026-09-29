"""Shared test fakes: ChunkStore / embed_fn / generate_fn stand-ins used at
both the rag seam (test_rag) and the API seam (test_ask). Everything here is
in-memory — no fake touches OpenRouter or Atlas (spec's Testing Decisions).
"""
from collections.abc import Mapping, Sequence

from app.config import ProviderConfig, RetrievalConfig
from app.ingest import IngestMeta

TEST_PROVIDER_CONFIG = ProviderConfig(
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


def hit(index: int, text: str) -> dict[str, object]:
    """A store hit in the shape AtlasChunkStore.search projects."""
    return {
        "text": text,
        "source": "eu-ai-act.pdf",
        "page": 12 + index,
        "chunk_index": index,
        "score": 0.9 - index / 10,
    }


def recording_embed(vectors_by_call: list[list[list[float]]]):
    """An embed_fn stand-in returning pre-set vectors per call, recording inputs."""
    calls: list[list[str]] = []

    def embed_fn(texts, *, config):
        calls.append(list(texts))
        return vectors_by_call[len(calls) - 1]

    embed_fn.calls = calls  # type: ignore[attr-defined]
    return embed_fn


def question_embed(vectors: list[list[float]]):
    return recording_embed([vectors])


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