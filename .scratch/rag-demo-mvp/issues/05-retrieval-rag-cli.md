# 05: Retrieval + rag.py CLI

**What to build:** The first true end-to-end answer, without any UI: a retrievable Question goes to Atlas vector search (top-k = 4), the retrieved Chunks and the Question are assembled into a Prompt, and the streaming LLM answer prints with Citations (Document, page, verbatim Chunk text) — plus an honest Refusal when the Corpus doesn't support an answer. Driven from a CLI loop for debugging without the frontend.

**Blocked by:** 04 (ingestion — Atlas setup + store Chunks).

**Status:** resolved

- [x] Vector search returns top-k Chunks (k=4 default from config) for a Question's embedding
- [x] Prompt assembled per spec: system rules (answer only from context, cite Document+page, Refuse when unsupported), the Question, and the retrieved Chunks; low temperature
- [x] Streaming answer prints to the terminal; Citations (Document, page, verbatim Chunk) shown after
- [x] Refusal surfaces honestly when the Corpus doesn't cover the Question
- [x] CLI loop for iterative Question/answer debugging against the real pipeline
- [x] Free LLM fallback chain applies here too (single models tried in config order)

## Comments

- `app/rag.py` holds the pipeline the CLI drives today and the `/ask` endpoint (ticket 06) will reuse: `retrieve` (delegates to the new shared `app.ingest.search_question` — the same primitive `probe` uses), the pure `build_prompt` (system rules = answer only from excerpts, cite Document+page, refuse with exactly the spec's sentence), and the `ask` orchestrator (streams tokens via an `on_token` callback, returns an `Answer` with `citations` + `refused`). `Citation` = Document, page, chunk_index, verbatim text, score. Prompt tuning lives in a new `RetrievalConfig` (`app.config.load_retrieval_config`): `TOP_K` (default 4) and `ANSWER_TEMPERATURE` (default 0.2), env-overridable, blank-restores-default, malformed values raise clean errors naming the variable. `providers.generate()` gained an optional `temperature` param — omitted from the request body when not given, so the old wire shape is untouched.
- Refusal is two-layered: **programmatic** — empty retrieval returns the spec's "I couldn't find that in the documents." without spending an LLM request from the shared free daily cap; **model-level** — the Prompt names that exact sentence as the required unsupported-answer reply. Verified live both ways (an out-of-scope question got the refusal sentence even though vector search always returns top-k hits; retrieval has no score threshold — the model is the judge).
- CLI: `python -m app.cli ask "question"` (one-shot) / `python -m app.cli ask` (interactive loop, empty line or Ctrl-C exits). Chain attempts print to stderr (live: qwen 429 → gemma 429 → nemotron answered — the fallback chain demonstrably works). Citations print after the stream, full verbatim Chunk text.
- Live-run bug: Windows consoles run cp1252, which cannot map characters the models emit (U+2011 non-breaking hyphen) — `print` crashed mid-stream. Fixed with `cli._safe_print` (unencodable characters become `?`), pinned by a unit test against a real cp1252 `TextIOWrapper`.
- Code-review fixes (6 findings, 5 accepted): `load_retrieval_config` now validates — blank values restore defaults, non-numeric or out-of-range values (`TOP_K=0`/-3, `ANSWER_TEMPERATURE=5`) raise clean config errors instead of crashing raw or silently refusing every question; Ctrl-C during a streaming answer exits cleanly instead of a traceback (loop and one-shot); the `embed` command maps a bad vector count to a clean `EmbeddingError` instead of a raw unpack crash; `retrieve` reuses the extracted `search_question` instead of duplicating `probe`'s logic; dead `Answer` import removed. Declined with rationale: re-wrapping `IngestError` as a retrieval-specific type — the `ChunkStore` protocol lives in `app.ingest` and its `search` contract raises `IngestError`, so store failures arriving as `IngestError` is the established seam contract; the `/ask` endpoint (ticket 06) can map error families at its own boundary.
- 61 tests passing, mypy clean. Live-verified: in-scope question streams a cited answer (Article 16 obligations from p.62, score 0.90), out-of-scope question refuses with the exact spec sentence, config error paths are clean, fallback chain works live.
