# 04: Ingestion — Atlas setup + store Chunks

**What to build:** Running the one-off ingestion script against the real Corpus populates a MongoDB Atlas free cluster: Chunks embedded via the provider wrapper in batched calls and stored with full metadata, with an Atlas Vector Search index that a query can hit. Changing the embedding model in config and re-running re-stores everything cleanly instead of mixing incompatible vectors.

**Blocked by:** 02 (provider wrappers + config) + 03 (chunker).

**Status:** resolved

- [x] Atlas free cluster reachable; connection string from backend env only
- [x] Vector search index created/managed by the ingest script (one index; respects free-tier index limits)
- [x] Chunks embedded in batched array calls (conservative batch size for the undocumented payload ceiling), inside the free daily request cap
- [x] Every Chunk stored with text, embedding, source, page, chunk_index, embedding_model, dim (per ADR-0002)
- [x] Model/dim change in config triggers drop-and-recreate of index and collection, never a silent mix
- [x] Verifiable: ingest run completes; collection populated; a manual vector search against the index returns relevant Chunks

## Comments

- `app/ingest.py` holds the decisions (batching `EMBED_BATCH_SIZE=32` for the HTTP 413 ceiling, document shape, reset policy, the orchestrator, the `probe`); `app/atlas.py` is the thin pymongo `ChunkStore` implementation behind the protocol (env-only `MONGODB_URI`, one `vectorSearch` index named `chunk_vector_index`, index-ready polling at up to 180s). `CLI: python -m app.ingest <pdf> [--force]` / `--check QUESTION`. All pymongo failures surface as clean `IngestError` messages. `pymongo>=4.10` added to requirements.
- Live verification: `python -m app.ingest ../corpus/eu-ai-act.pdf` → `ingested: 435 chunks, model liquid/lfm-2.5-embedding-350m:free, dim 1024`; re-run reports `skipped`; `--check "Which obligations apply to providers of high-risk AI systems?"` returned top cosine 0.90 against Article 16 obligations text. Intermittent DNS timeouts (local resolver + UDP/53 flakiness) delayed the first runs; nothing code-side.
- Two real bugs the live run + tests caught: (1) `python -m app.ingest` double-module trap — the CLI's `except (IngestError, ...)` bound its own `__main__` copy of `IngestError` while `app.atlas` raised `app.ingest`'s, so stack traces leaked; fixed by rebinding the canonical class in `__main__`, pinned by a subprocess test that runs the real CLI with a bad URI (no network). (2) The chunker's 4-chars/token estimate undershot the model's real tokenizer by >10% (549 actual vs ≤500 estimated), blowing the model's 512-token ceiling with HTTP 400s; the default now budgets at ~3 chars/token, pinned by a headroom regression test in `test_chunker.py` (ticket 03's seam).
- Code-review fixes (8 findings triaged): skip path now probe-embeds one chunk to verify dim (same-model dim drift resets, never silently skips — ADR-0002) and still calls `ensure_index` so a prior failed index build gets repaired; empty provider responses (200 with no vectors) are clean `IngestError`s instead of `IndexError`/`ValueError`; `ensure_index` compares the stored index definition and updates a stale one instead of accepting it on name alone; `state()` refuses to skip over metadata-less documents (corrupt collection = clean error); `reset()` drops the collection only (its index goes with it); `run_ingestion` takes explicit typed kwargs; stale comments corrected (4→3 chars/token arithmetic in `EMBED_BATCH_SIZE` rationale and test comments); mypy errors fixed (protocol-matching fake signatures, narrowing, `dict[str, Any]` cast in the CLI print). Accepted trade-offs documented in code: delete-then-insert `replace_documents` is non-atomic (M0 has no transactions) but self-heals via the count check; per-batch TLS handshakes not reused (one-off script; the fake seam would need an awkward signature).
- 43 tests passing, mypy clean. Live ingest + skip + `--check` all verified against the real cluster.