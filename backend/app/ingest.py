"""Ingestion: turn the Corpus PDF into stored Chunks with embeddings.

Pure logic lives here (batching, document shape, reset decisions, the
orchestrator); the pymongo/Atlas glue lives in ``app.atlas`` behind the
``ChunkStore`` protocol, so everything testable is tested with fakes and no
test ever touches OpenRouter or Atlas for real (spec's Testing Decisions).

Run from ``backend/``::

    python -m app.ingest ../corpus/eu-ai-act.pdf [--force]
    python -m app.ingest --check "What is the AI Act?"
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.chunker import Chunk, chunk_pages, parse_pdf, strip_annexes
from app.config import ProviderConfig
from app.providers import embed

# The embeddings endpoint has an undocumented payload ceiling (spec's Further
# Notes: HTTP 413); ~500-token Chunks (~1500 chars at the chunker's 3-chars/token
# estimate) mean 32 of them is ~48 KB of text — conservative and still one
# request per ~32 Chunks, inside the free daily cap.
EMBED_BATCH_SIZE = 32


class IngestError(Exception):
    """A clean, user-facing ingestion failure (no stack traces leak past this)."""


@dataclass(frozen=True)
class IngestMeta:
    """The per-corpus embedding identity recorded on every Chunk (ADR-0002)."""

    embedding_model: str
    dim: int


@dataclass(frozen=True)
class IngestReport:
    """What one ingestion run did, for the CLI to print."""

    source: str
    chunks: int
    model: str
    dim: int
    action: str  # "ingested" | "reset+ingested" | "skipped"


class ChunkStore(Protocol):
    """Where ingested Chunks live. ``app.atlas.AtlasChunkStore`` implements this."""

    def state(self) -> tuple[IngestMeta | None, int]:
        """(stored embedding meta or None, stored document count)."""
        ...

    def reset(self) -> None:
        """Drop everything: incompatible vectors must not survive (ADR-0002)."""
        ...

    def replace_documents(self, docs: Sequence[Mapping[str, object]]) -> None:
        """Replace the collection's contents with ``docs``."""
        ...

    def ensure_index(self, definition: Mapping[str, object]) -> None:
        """Make sure a vector index matching ``definition`` exists and is queryable."""
        ...

    def search(self, vector: Sequence[float], k: int) -> list[dict[str, object]]:
        """Top-k Chunks by vector similarity — the verification probe."""
        ...


def embed_chunks(
    chunks: Sequence[Chunk],
    *,
    config: ProviderConfig,
    batch_size: int = EMBED_BATCH_SIZE,
    embed_fn: Callable[..., list[list[float]]] = embed,
) -> list[list[float]]:
    """Embed Chunks in batched array calls; vectors come back in chunk order."""
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start:start + batch_size]
        vectors.extend(embed_fn([c.text for c in batch], config=config))
    return vectors


def chunk_documents(
    chunks: Sequence[Chunk],
    vectors: Sequence[Sequence[float]],
    meta: IngestMeta,
) -> list[dict[str, object]]:
    """Build the stored document shape: the PRD data model, verbatim."""
    if len(vectors) != len(chunks):
        raise IngestError(
            f"Embedding returned {len(vectors)} vectors for {len(chunks)} chunks"
        )
    return [
        {
            "text": chunk.text,
            "embedding": list(vector),
            "source": chunk.source,
            "page": chunk.page,
            "chunk_index": chunk.chunk_index,
            "embedding_model": meta.embedding_model,
            "dim": meta.dim,
        }
        for chunk, vector in zip(chunks, vectors)
    ]


def vector_index_definition(dim: int) -> dict[str, object]:
    """The Atlas Vector Search index definition: one cosine field on ``embedding``."""
    return {
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": dim,
                "similarity": "cosine",
            }
        ]
    }


def needs_reset(stored: IngestMeta, new: IngestMeta) -> bool:
    """True when the stored Chunks and the configured embedding are incompatible.

    Different model or dimension can never share one vector index (ADR-0002):
    the caller must drop-and-recreate instead of mixing vectors.
    """
    return stored != new


def ingest_chunks(
    chunks: Sequence[Chunk],
    *,
    config: ProviderConfig,
    store: ChunkStore,
    embed_fn: Callable[..., list[list[float]]] = embed,
    batch_size: int = EMBED_BATCH_SIZE,
    force: bool = False,
    log: Callable[[str], None] = print,
) -> IngestReport:
    """Embed and store Chunks, keeping model/dim identity coherent (ADR-0002).

    Embedding happens before any store mutation, so a provider failure loses
    nothing. A stored corpus with the same model, a probe-confirmed dim, and
    the same chunk count is a no-op (``force`` overrides) — but the skip path
    still ensures the index, so a prior run that failed during index creation
    gets repaired. A model or dim change resets the store first, then
    re-stores — never a silent mix of incompatible vectors.
    """
    if not chunks:
        raise IngestError("No Chunks to ingest — the Corpus produced no text")

    stored_meta, stored_count = store.state()
    if (
        not force
        and stored_meta is not None
        and stored_meta.embedding_model == config.embedding_model
        and stored_count == len(chunks)
    ):
        # One cheap probe embed verifies the model's current dim against the
        # store: a same-model-ID dim change must reset, never silently skip
        # over a mixed store (ADR-0002).
        probe_result = embed_fn([chunks[0].text], config=config)
        if len(probe_result) != 1:
            raise IngestError(
                f"Embedding returned {len(probe_result)} vectors for 1 probe chunk"
            )
        if len(probe_result[0]) == stored_meta.dim:
            store.ensure_index(vector_index_definition(stored_meta.dim))
            log(
                f"Already ingested: {stored_count} chunks with "
                f"{stored_meta.embedding_model!r} (dim {stored_meta.dim}). "
                "Use --force to re-embed."
            )
            return IngestReport(
                source=chunks[0].source,
                chunks=stored_count,
                model=stored_meta.embedding_model,
                dim=stored_meta.dim,
                action="skipped",
            )
        log(
            f"Embedding dim changed ({stored_meta.dim} -> {len(probe_result[0])} "
            f"under the same model {stored_meta.embedding_model!r})"
        )

    log(f"Embedding {len(chunks)} chunks with {config.embedding_model!r}...")
    vectors = embed_chunks(chunks, config=config, batch_size=batch_size, embed_fn=embed_fn)
    if not vectors:
        raise IngestError("Embedding returned no vectors")
    meta = IngestMeta(embedding_model=config.embedding_model, dim=len(vectors[0]))

    action = "ingested"
    if stored_meta is not None and needs_reset(stored_meta, meta):
        log(
            f"Embedding changed ({stored_meta.embedding_model!r} dim "
            f"{stored_meta.dim} -> {meta.embedding_model!r} dim {meta.dim}): "
            "dropping index and collection"
        )
        store.reset()
        action = "reset+ingested"

    store.replace_documents(chunk_documents(chunks, vectors, meta))
    store.ensure_index(vector_index_definition(meta.dim))
    log(f"Stored {len(chunks)} chunks; vector index ensured (dim {meta.dim})")
    return IngestReport(
        source=chunks[0].source,
        chunks=len(chunks),
        model=meta.embedding_model,
        dim=meta.dim,
        action=action,
    )


def run_ingestion(
    pdf_path: Path,
    *,
    config: ProviderConfig,
    store: ChunkStore,
    embed_fn: Callable[..., list[list[float]]] = embed,
    batch_size: int = EMBED_BATCH_SIZE,
    force: bool = False,
    log: Callable[[str], None] = print,
) -> IngestReport:
    """The one-off script's core: Corpus PDF -> Chunks -> stored vectors.

    Thin glue like the chunker's ``parse_pdf``: parsing, annex stripping, and
    windowing feed the testable ``ingest_chunks``.
    """
    pages = strip_annexes(parse_pdf(pdf_path))
    chunks = chunk_pages(pages, source=pdf_path.name)
    return ingest_chunks(
        chunks,
        config=config,
        store=store,
        embed_fn=embed_fn,
        batch_size=batch_size,
        force=force,
        log=log,
    )


def search_question(
    question: str,
    *,
    config: ProviderConfig,
    store: ChunkStore,
    embed_fn: Callable[..., list[list[float]]] = embed,
    k: int = 5,
) -> list[dict[str, object]]:
    """Embed one Question and search the store for its top-k Chunks.

    The shared primitive of the ingest-time ``probe`` and ask-time retrieval
    (``app.rag.retrieve``): one embed, one vector search, store order.
    """
    result = embed_fn([question], config=config)
    if len(result) != 1:
        raise IngestError(f"Embedding returned {len(result)} vectors for one question")
    return store.search(result[0], k)


def probe(
    question: str,
    *,
    config: ProviderConfig,
    store: ChunkStore,
    embed_fn: Callable[..., list[list[float]]] = embed,
    k: int = 5,
) -> list[dict[str, object]]:
    """Embed one Question and search the store — the manual verification probe."""
    return search_question(question, config=config, store=store, embed_fn=embed_fn, k=k)


if __name__ == "__main__":
    import argparse
    import sys
    from typing import Any, cast

    from app.atlas import AtlasChunkStore
    from app.config import load_provider_config
    # ``python -m`` loads this file as ``__main__`` while app.atlas imports
    # ``app.ingest`` — two module objects. Rebind to the canonical classes the
    # store raises, or the except clause below never fires and stack traces leak.
    from app.ingest import IngestError as IngestError
    from app.providers import ProviderError

    parser = argparse.ArgumentParser(
        prog="ingest",
        description="One-off ingestion: Corpus PDF -> Atlas chunks + vector index.",
    )
    parser.add_argument("pdf", nargs="?", type=Path, help="the Corpus PDF to ingest")
    parser.add_argument("--force", action="store_true", help="re-embed even if unchanged")
    parser.add_argument("--check", metavar="QUESTION", help="embed QUESTION, search the index")
    parser.add_argument("--k", type=int, default=5, help="hits shown by --check")
    args = parser.parse_args()
    if bool(args.pdf) == bool(args.check):
        parser.error("give exactly one of: a PDF path, or --check QUESTION")

    config = load_provider_config()
    try:
        store = AtlasChunkStore.from_env()
        if args.check:
            for raw_hit in probe(args.check, config=config, store=store, k=args.k):
                # Atlas projects these keys; cast so the CLI can format them.
                hit = cast(dict[str, Any], raw_hit)
                preview = hit["text"][:100] + ("..." if len(hit["text"]) > 100 else "")
                print(f"  {hit['score']:.4f}  {hit['source']} p.{hit['page']} "
                      f"[{hit['chunk_index']}]: {preview}")
        else:
            report = run_ingestion(args.pdf, config=config, store=store, force=args.force)
            print(f"{report.action}: {report.chunks} chunks, "
                  f"model {report.model}, dim {report.dim}")
    except (IngestError, ProviderError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
