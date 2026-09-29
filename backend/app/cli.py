"""Debug CLI: exercise the provider seam without the UI or the API layer.

Run from ``backend/`` with a real key in ``.env``::

    python -m app.cli embed "some text"
    python -m app.cli generate "What is the AI Act?"

``generate`` prints each fallback-chain attempt to stderr, so you can watch
the chain try models in order when one is missing or rate-limited.
"""
from __future__ import annotations

import argparse
import sys

from app.config import load_provider_config
from app.providers import ProviderError, embed, generate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rag", description="Exercise embedding and generation from the CLI."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    embed_parser = subparsers.add_parser("embed", help="embed a string, print the vector")
    embed_parser.add_argument("text")
    generate_parser = subparsers.add_parser("generate", help="stream an answer from a Prompt")
    generate_parser.add_argument("prompt")
    args = parser.parse_args(argv)

    config = load_provider_config()
    try:
        if args.command == "embed":
            (vector,) = embed([args.text], config=config)
            print(f"model: {config.embedding_model}, dim: {len(vector)}")
            print(vector)
        else:
            for token in generate(args.prompt, config=config, on_attempt=_report_attempt):
                print(token, end="", flush=True)
            print()
    except ProviderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _report_attempt(model: str, reason: str | None) -> None:
    if reason is None:
        print(f"[chain] {model}: answering", file=sys.stderr)
    else:
        print(f"[chain] {model}: {reason} - trying next", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
