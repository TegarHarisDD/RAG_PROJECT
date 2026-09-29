# MongoDB Atlas M0 with per-chunk embedding metadata

Chunks are stored in MongoDB Atlas's free M0 cluster using Atlas Vector Search (max 3 indexes, 512 MB, ≤8,192 dims — all comfortably sufficient for one small corpus), and every chunk document records `embedding_model` and `dim` alongside its vector. This makes the embedding model an explicit, swappable part of the data: changing models means re-running ingestion and re-creating the vector index, never a silent mix of incompatible vectors in one index. No other database, no Celery/Redis, no auth — ingestion is a one-off script.

## Consequences

- Re-ingesting invalidates the old vector index (dimension/model change), so the ingestion script must handle drop-and-recreate or a new index version.
- A tiny corpus plus int8/binary automatic quantization keeps the M0 in-memory vector index small.
