"""Retrieval + generation: a Question becomes a streamed, cited answer.

The pipeline the debug CLI (``python -m app.cli ask``) drives today and the
``/ask`` endpoint reuses next: embed the Question, pull the top-k Chunks from
the store, assemble the Prompt (system rules + Question + verbatim Chunks),
then stream tokens through the provider fallback chain. The decisions live
here and are tested with fakes; Atlas and OpenRouter HTTP stay behind the
``ChunkStore`` and provider seams (spec's Testing Decisions) — no test touches
the network for real.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

from app.config import ProviderConfig, RetrievalConfig
from app.ingest import ChunkStore, search_question
from app.providers import embed, generate

# The honest out-of-scope answer (spec user story 5). Used verbatim for the
# empty-retrieval Refusal and named in the Prompt, so the model's refusals and
# the programmatic one read identically.
REFUSAL_MESSAGE = "I couldn't find that in the documents."


@dataclass(frozen=True)
class Citation:
    """The pointer shown with an answer: Document, page, verbatim Chunk text."""

    source: str
    page: int
    chunk_index: int
    text: str
    score: float


@dataclass(frozen=True)
class Answer:
    """What one Question produced: the streamed text plus its evidence."""

    question: str
    text: str
    citations: tuple[Citation, ...]
    refused: bool  # refused before asking the LLM: retrieval found nothing


def retrieve(
    question: str,
    *,
    config: ProviderConfig,
    retrieval: RetrievalConfig,
    store: ChunkStore,
    embed_fn: Callable[..., list[list[float]]] = embed,
) -> tuple[Citation, ...]:
    """Embed the Question and return the top-k Chunks (k from config), in the
    store's similarity order.

    Failures from the store seam raise ``IngestError`` — that is the
    ``ChunkStore`` contract, which lives in ``app.ingest`` — so callers handle
    retrieval and store errors with the same clean-error family.
    """
    return tuple(
        Citation(
            source=str(h["source"]),
            page=int(h["page"]),  # type: ignore[call-overload]
            chunk_index=int(h["chunk_index"]),  # type: ignore[call-overload]
            text=str(h["text"]),
            score=float(h["score"]),  # type: ignore[arg-type]
        )
        for h in search_question(
            question, config=config, store=store, embed_fn=embed_fn, k=retrieval.top_k
        )
    )


def build_prompt(question: str, citations: Sequence[Citation]) -> str:
    """Assemble the Prompt: system rules, the Question, the verbatim Chunks.

    Pure function. The rules are the spec's three: answer only from context,
    cite Document+page, Refuse when the Chunks don't support an answer — with
    the refusal phrased as ``REFUSAL_MESSAGE`` so every refusal reads the same.
    """
    excerpts = "\n\n".join(
        f"[{i}] {c.source} p.{c.page}\n{c.text}"
        for i, c in enumerate(citations, start=1)
    )
    return (
        "You are answering a question about a fixed set of documents (the Corpus).\n"
        "\n"
        "Rules:\n"
        "- Answer ONLY from the excerpts below. Never use outside knowledge, and never guess.\n"
        "- Cite the Document and page for each claim, in the form (source.pdf, p. N).\n"
        "- If the excerpts do not contain the information needed to answer, reply with\n"
        f"  exactly this sentence and nothing else: {REFUSAL_MESSAGE}\n"
        "\n"
        f"Question: {question}\n"
        "\n"
        f"Excerpts:\n{excerpts}"
    )


def ask(
    question: str,
    *,
    config: ProviderConfig,
    retrieval: RetrievalConfig,
    store: ChunkStore,
    embed_fn: Callable[..., list[list[float]]] = embed,
    generate_fn: Callable[..., Iterator[str]] = generate,
    on_token: Callable[[str], None] | None = None,
    on_attempt: Callable[[str, str | None], None] | None = None,
) -> Answer:
    """One end-to-end turn: retrieve, assemble the Prompt, stream the answer.

    Tokens flow to ``on_token`` as they arrive (the CLI prints them; the API
    will forward them as SSE events), while ``on_attempt`` reaches the
    provider chain unchanged so the fallback stays observable. When retrieval
    finds nothing, the Refusal is returned without an LLM call — the shared
    free daily cap is not spent on a question the Corpus cannot answer
    (ADR-0001). When generation fails, the ``GenerationError`` propagates to
    the caller's error boundary.
    """
    citations = retrieve(
        question, config=config, retrieval=retrieval, store=store, embed_fn=embed_fn
    )
    if not citations:
        return Answer(
            question=question, text=REFUSAL_MESSAGE, citations=(), refused=True
        )

    tokens: list[str] = []
    for token in generate_fn(
        build_prompt(question, citations),
        config=config,
        temperature=retrieval.temperature,
        on_attempt=on_attempt,
    ):
        tokens.append(token)
        if on_token:
            on_token(token)
    return Answer(
        question=question, text="".join(tokens), citations=citations, refused=False
    )