# 03: Chunker (pure function)

**What to build:** A pure function that turns the Corpus PDF into Chunks: parse the official EU AI Act PDF (regulation body Articles only, annexes excluded), split into ~500-token Chunks with ~80-token overlap, and carry page numbers through so every Chunk knows its Document and page. Verifiable by running it on the Corpus and eyeballing page-aligned output.

**Blocked by:** 01 (project skeleton + health endpoint). Independent of 02 — both can run in parallel.

**Status:** resolved

- [x] PDF parsed with pypdf (per ADR and spec licensing decision), page text extracted page by page
- [x] Chunks are ~500 tokens with ~80-token overlap; page mapping survives splitting (a Chunk knows its source page(s))
- [x] Regulation body only: annexes excluded from the output
- [x] Pure function — no network, no database; unit tests cover token counts, overlap, and page mapping
- [x] Verifiable: run on the Corpus and inspect Chunk text against PDF page numbers

## Comments

- `app/chunker.py`: `parse_pdf` (thin pypdf glue, one text per page), `strip_annexes` (cuts at the first standalone uppercase `ANNEX <N>` heading — case-sensitive so TOC mentions never trigger), and the pure `chunk_pages(pages, source=...)` → `Chunk(text, source, page, chunk_index)`. Word-level page tagging means page mapping survives splitting; a Chunk's `page` is where its text starts (spec data model keeps a single `page` field). Token sizing defaults to a ~4-chars/token heuristic (`DEFAULT_MAX_TOKENS=500`, `DEFAULT_OVERLAP_TOKENS=80`); tests inject an exact word counter so budgets are deterministic.
- The CLI smoke (`python -m app.chunker <pdf>`) caught a real bug the unit tests missed: once the final window reached the end of the word supply, the loop re-emitted near-duplicate tail windows (65 chunks instead of 2). Fixed with a stop after the last window; a regression test pins it.
- 9 chunker tests + full suite 23 passing, mypy clean. Real-Corpus verification awaits the PDF (ticket 04 setup); the `__main__` aid prints body-page count, token stats, and sample chunks with pages for eyeballing.
- Code-review fixes: annex cut moved to heading granularity (body articles sharing the annex's first page survive); heading regex relaxed to a prefix match so extraction-merged "ANNEX I Title" lines still trigger the cut (case-sensitive, so TOC mentions stay safe); `ValueError` when `overlap_tokens >= max_tokens` (would otherwise slide one word at a time); default chars/token counter now uses prefix sums (window probing O(n), not O(n²)); dead code removed in the `__main__` aid. Status vocabulary across tickets 01–03 aligned to `resolved` per `docs/agents/triage-labels.md`. 26 tests passing, mypy clean.
- Incident from the same review: a live OpenRouter key and Atlas URI were briefly pasted into the tracked `backend/.env.example` (uncommitted). Both moved to the git-ignored `backend/.env` and the template restored; **both credentials should be rotated** since they left the .env boundary. Live verification with the key confirmed the embedding model `liquid/lfm-2.5-embedding-350m:free` resolves and returns 1024-dim vectors, exactly per spec.
