"""Chunker: turn page texts into Chunks (~500 tokens, ~80 overlap).

Pure functions only — no network, no database — so the boundary is unit-tested
directly (see the spec's Testing Decisions). ``parse_pdf`` is the one thin I/O
glue (pypdf, per the spec's licensing decision); everything else operates on
plain page texts.

Chunks are stored text normalized to single spaces: a Chunk's text is what a
Citation shows verbatim. A Chunk's ``page`` is the page its text starts on.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import accumulate
from pathlib import Path

import pypdf

# ~4 characters per token is the standard heuristic for English prose; the
# exact tokenizer of the free embedding model is unknown, and the spec's
# "~500 tokens / ~80 overlap" targets are approximate by design.
DEFAULT_MAX_TOKENS = 500
DEFAULT_OVERLAP_TOKENS = 80

# A heading like "ANNEX I", standalone or followed by its title — pypdf often
# merges both onto one extracted line. Case-sensitive so a table-of-contents
# line ("Annex I on page 100") never triggers the cut.
_ANNEX_HEADING = re.compile(r"^\s*ANNEX\s+[IVXLCDM0-9]+(?:\s|$)", re.MULTILINE)


@dataclass(frozen=True)
class Chunk:
    """A contiguous span of a Document, ready for embedding and citation."""

    text: str
    source: str
    page: int
    chunk_index: int


def parse_pdf(path: Path) -> list[str]:
    """Extract one text string per page, in page order (pypdf, BSD-licensed)."""
    reader = pypdf.PdfReader(path)
    return [page.extract_text() or "" for page in reader.pages]


def strip_annexes(pages: Sequence[str]) -> list[str]:
    """Keep the regulation body only: drop everything from the first ANNEX heading.

    The cut is at the heading, not the page: articles sharing a page with the
    annex start survive up to the heading.
    """
    body: list[str] = []
    for page_text in pages:
        match = _ANNEX_HEADING.search(page_text)
        if match:
            head = page_text[: match.start()].rstrip()
            if head:
                body.append(head)
            break
        body.append(page_text)
    return body


def chunk_pages(
    pages: Sequence[str],
    *,
    source: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    count_tokens: Callable[[str], int] | None = None,
) -> list[Chunk]:
    """Split page texts into sliding-window Chunks.

    Words are tagged with the page they came from, so page mapping survives
    splitting. Each window is the largest span within ``max_tokens``; the next
    window starts ~``overlap_tokens`` earlier so spans straddle boundaries.
    Blank pages contribute no words and no chunks.
    """
    if overlap_tokens >= max_tokens:
        raise ValueError(
            f"overlap_tokens ({overlap_tokens}) must be smaller than "
            f"max_tokens ({max_tokens}), or windows stop advancing"
        )
    counter = _default_count_tokens if count_tokens is None else count_tokens

    words: list[tuple[str, int]] = [
        (word, page_number)
        for page_number, page_text in enumerate(pages, start=1)
        for word in page_text.split()
    ]
    measure = _measure_for(words, counter)

    chunks: list[Chunk] = []
    start = 0
    while start < len(words):
        end = _window_end(measure, start, len(words), max_tokens)
        chunks.append(
            Chunk(
                text=_text(words, start, end),
                source=source,
                page=words[start][1],
                chunk_index=len(chunks),
            )
        )
        if end >= len(words):  # last window reached the corpus end — stop here
            break
        start = max(_overlap_start(measure, end, overlap_tokens), start + 1)
    return chunks


def _measure_for(
    words: Sequence[tuple[str, int]], counter: Callable[[str], int]
) -> Callable[[int, int], int]:
    """Token size of words[start:end] as a cheap index-based probe.

    The default chars-per-token counter gets an O(1) prefix-sum path (window
    probing stays O(n) over the whole corpus); a custom counter probes via the
    span text instead.
    """
    if counter is _default_count_tokens:
        char_sums = list(accumulate((len(word) for word, _ in words), initial=0))

        def measure_by_prefix(start: int, end: int) -> int:
            chars = char_sums[end] - char_sums[start] + (end - start - 1)
            return max(1, chars // 4)

        return measure_by_prefix

    def measure_by_text(start: int, end: int) -> int:
        return counter(_text(words, start, end))

    return measure_by_text


def _default_count_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _window_end(
    measure: Callable[[int, int], int], start: int, end_limit: int, max_tokens: int
) -> int:
    """Largest ``end`` such that words[start:end] fits the token budget.

    The first word always makes the window, even over budget — progress is
    guaranteed no matter what a caller passes.
    """
    end = start + 1
    while end < end_limit and measure(start, end + 1) <= max_tokens:
        end += 1
    return end


def _overlap_start(
    measure: Callable[[int, int], int], end: int, overlap_tokens: int
) -> int:
    """Smallest ``start`` such that the tail words[start:end] is ~overlap tokens."""
    start = end
    while start > 0 and measure(start - 1, end) <= overlap_tokens:
        start -= 1
    return start


def _text(words: Sequence[tuple[str, int]], start: int, end: int) -> str:
    return " ".join(word for word, _ in words[start:end])


if __name__ == "__main__":
    # Eyeball aid: run on the Corpus PDF and check Chunk text against the PDF's
    # own page numbers, e.g.  python -m app.chunker corpus.pdf
    import argparse
    import statistics

    parser = argparse.ArgumentParser(description="Chunk a PDF and print a summary.")
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()

    document = args.pdf.name
    pages = strip_annexes(parse_pdf(args.pdf))
    chunks = chunk_pages(pages, source=document)
    sizes = [_default_count_tokens(chunk.text) for chunk in chunks]

    print(f"{document}: {len(pages)} body pages, {len(chunks)} chunks")
    if sizes:
        print(f"tokens/chunk: median {statistics.median(sizes):.0f}, "
              f"min {min(sizes)}, max {max(sizes)}")
        for chunk in chunks[:3]:
            preview = chunk.text[:100] + ("..." if len(chunk.text) > 100 else "")
            print(f"  [{chunk.chunk_index}] page {chunk.page}: {preview}")
        last = chunks[-1]
        if last.chunk_index >= 3:
            preview = last.text[:100] + ("..." if len(last.text) > 100 else "")
            print(f"  ... [{last.chunk_index}] page {last.page}: {preview}")
