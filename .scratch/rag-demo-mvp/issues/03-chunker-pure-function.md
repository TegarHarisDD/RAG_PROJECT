# 03: Chunker (pure function)

**What to build:** A pure function that turns the Corpus PDF into Chunks: parse the official EU AI Act PDF (regulation body Articles only, annexes excluded), split into ~500-token Chunks with ~80-token overlap, and carry page numbers through so every Chunk knows its Document and page. Verifiable by running it on the Corpus and eyeballing page-aligned output.

**Blocked by:** 01 (project skeleton + health endpoint). Independent of 02 — both can run in parallel.

**Status:** ready-for-agent

- [ ] PDF parsed with pypdf (per ADR and spec licensing decision), page text extracted page by page
- [ ] Chunks are ~500 tokens with ~80-token overlap; page mapping survives splitting (a Chunk knows its source page(s))
- [ ] Regulation body only: annexes excluded from the output
- [ ] Pure function — no network, no database; unit tests cover token counts, overlap, and page mapping
- [ ] Verifiable: run on the Corpus and inspect Chunk text against PDF page numbers
