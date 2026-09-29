# 04: Ingestion — Atlas setup + store Chunks

**What to build:** Running the one-off ingestion script against the real Corpus populates a MongoDB Atlas free cluster: Chunks embedded via the provider wrapper in batched calls and stored with full metadata, with an Atlas Vector Search index that a query can hit. Changing the embedding model in config and re-running re-stores everything cleanly instead of mixing incompatible vectors.

**Blocked by:** 02 (provider wrappers + config) + 03 (chunker).

**Status:** ready-for-agent

- [ ] Atlas free cluster reachable; connection string from backend env only
- [ ] Vector search index created/managed by the ingest script (one index; respects free-tier index limits)
- [ ] Chunks embedded in batched array calls (conservative batch size for the undocumented payload ceiling), inside the free daily request cap
- [ ] Every Chunk stored with text, embedding, source, page, chunk_index, embedding_model, dim (per ADR-0002)
- [ ] Model/dim change in config triggers drop-and-recreate of index and collection, never a silent mix
- [ ] Verifiable: ingest run completes; collection populated; a manual vector search against the index returns relevant Chunks
