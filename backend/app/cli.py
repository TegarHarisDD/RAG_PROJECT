"""Debug CLI: exercise the pipeline without the UI or the API layer.

Run from ``backend/`` with a real key in ``.env``::

    python -m app.cli embed "some text"
    python -m app.cli generate "What is the AI Act?"
    python -m app.cli ask "What is the AI Act?"   # one-shot
    python -m app.cli ask                          # interactive Question loop

``generate`` and ``ask`` print each fallback-chain attempt to stderr, so you
can watch the chain try models in order when one is missing or rate-limited.
``ask`` runs the full retrieval pipeline (``app.rag``): top-k Chunks from
Atlas, a streamed answer, then Citations (Document, page, verbatim Chunk).
"""
from __future__ import annotations

import argparse
import sys
from typing import TextIO

from app.atlas import AtlasChunkStore
from app.config import ProviderConfig, RetrievalConfig, load_provider_config, load_retrieval_config
from app.ingest import IngestError
from app.providers import EmbeddingError, ProviderError, embed, generate
from app.rag import ask


def _safe_print(text: str, *, stream: TextIO | None = None, end: str = "\n") -> None:
    """Print text, replacing characters the console cannot encode.

    Windows terminals often run cp1252, which cannot map characters the models
    emit (e.g. the non-breaking hyphen U+2011) — printing would crash
    mid-answer. Unencodable characters become ``?`` instead.
    """
    out = stream or sys.stdout
    encoding = getattr(out, "encoding", None) or "ascii"
    try:
        out.write(text + end)
        out.flush()
    except UnicodeEncodeError:
        out.write(text.encode(encoding, "replace").decode(encoding) + end)
        out.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rag", description="Exercise embedding, generation, and RAG from the CLI."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    embed_parser = subparsers.add_parser("embed", help="embed a string, print the vector")
    embed_parser.add_argument("text")
    generate_parser = subparsers.add_parser("generate", help="stream an answer from a Prompt")
    generate_parser.add_argument("prompt")
    ask_parser = subparsers.add_parser(
        "ask", help="retrieve Chunks and stream a cited answer; a loop with no question"
    )
    ask_parser.add_argument("question", nargs="?", help="omit to enter the interactive loop")
    args = parser.parse_args(argv)

    config = load_provider_config()
    try:
        if args.command == "embed":
            vectors = embed([args.text], config=config)
            if len(vectors) != 1:
                raise EmbeddingError(
                    f"Embedding returned {len(vectors)} vectors for one text"
                )
            (vector,) = vectors
            print(f"model: {config.embedding_model}, dim: {len(vector)}")
            print(vector)
        elif args.command == "generate":
            for token in generate(args.prompt, config=config, on_attempt=_report_attempt):
                _safe_print(token, end="")
            _safe_print("")
        else:
            return _ask_main(args.question, config=config)
    except ProviderError as exc:
        _safe_print(f"error: {exc}", stream=sys.stderr)
        return 1
    return 0


def _ask_main(question: str | None, *, config: ProviderConfig) -> int:
    try:
        retrieval = load_retrieval_config()
        store = AtlasChunkStore.from_env()
        if question is None:
            return _ask_loop(config, retrieval, store)
        _run_ask(question, config=config, retrieval=retrieval, store=store)
    except (IngestError, ProviderError, ValueError) as exc:
        # ValueError: a malformed retrieval setting raised a clean config error.
        _safe_print(f"error: {exc}", stream=sys.stderr)
        return 1
    except KeyboardInterrupt:
        _safe_print("")
        return 0
    return 0


def _ask_loop(
    config: ProviderConfig, retrieval: RetrievalConfig, store: AtlasChunkStore
) -> int:
    """The iterative debugging loop: ask until an empty line or Ctrl-C."""
    _safe_print("RAG debug loop — an empty line or Ctrl-C exits.")
    while True:
        try:
            question = input("question> ").strip()
        except (EOFError, KeyboardInterrupt):
            _safe_print("")
            return 0
        if not question:
            return 0
        try:
            _run_ask(question, config=config, retrieval=retrieval, store=store)
        except (IngestError, ProviderError, ValueError) as exc:
            # One failed question ends that turn, not the session.
            _safe_print(f"error: {exc}", stream=sys.stderr)
        except KeyboardInterrupt:
            # Ctrl-C mid-stream aborts the answer — the loop exits as promised.
            _safe_print("")
            return 0


def _run_ask(
    question: str,
    *,
    config: ProviderConfig,
    retrieval: RetrievalConfig,
    store: AtlasChunkStore,
) -> None:
    result = ask(
        question,
        config=config,
        retrieval=retrieval,
        store=store,
        on_token=lambda token: _safe_print(token, end=""),
        on_attempt=_report_attempt,
    )
    _safe_print("")
    if result.refused:
        _safe_print(result.text)
    if result.citations:
        _safe_print("\nSources:")
        for i, citation in enumerate(result.citations, start=1):
            _safe_print(
                f"  [{i}] {citation.source} p.{citation.page} "
                f"(chunk {citation.chunk_index}, score {citation.score:.4f})"
            )
            # The Chunk text is shown verbatim — it may hold console-hostile
            # characters from the model output or the Corpus itself.
            _safe_print(f"      {citation.text}")


def _report_attempt(model: str, reason: str | None) -> None:
    if reason is None:
        _safe_print(f"[chain] {model}: answering", stream=sys.stderr)
    else:
        _safe_print(f"[chain] {model}: {reason} - trying next", stream=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())