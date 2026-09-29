"""Atlas glue: the pymongo implementation of the ingestion ``ChunkStore`` protocol.

This is the one place real MongoDB is spoken. It is deliberately thin — the
decisions (batching, reset policy, document shape, index definition) all live
in ``app.ingest`` and are tested there with fakes; this module is verified
against the live cluster (spec's Testing Decisions: no test calls Atlas).

All pymongo failures surface as clean ``IngestError`` messages — never stack
traces — mirroring the provider seam's error mapping.
"""
from __future__ import annotations

import os
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from pymongo.operations import SearchIndexModel

from app.ingest import IngestError, IngestMeta

# Free-tier constraint: max 3 search/vector indexes combined — this app uses
# exactly one, recreated on embedding changes (ADR-0002).
DEFAULT_COLLECTION = "chunks"
DEFAULT_INDEX_NAME = "chunk_vector_index"
DEFAULT_DATABASE = "rag_demo"

# Atlas index builds are asynchronous; free tier can take a minute or two.
_INDEX_READY_TIMEOUT_S = 180
_INDEX_POLL_INTERVAL_S = 3


class AtlasChunkStore:
    """Chunks in an Atlas collection with one vector search index on ``embedding``."""

    def __init__(
        self,
        client: MongoClient,
        database: str = DEFAULT_DATABASE,
        *,
        collection: str = DEFAULT_COLLECTION,
        index_name: str = DEFAULT_INDEX_NAME,
        connect: bool = True,
    ) -> None:
        self._client = client
        self._collection = client[database][collection]
        self._index_name = index_name
        if connect:
            self._ping()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AtlasChunkStore:
        """Build from ``MONGODB_URI`` (required) and ``MONGODB_DB`` — env only.

        The production path (``env=None``) loads ``backend/.env`` first. The
        connection string never appears in code or the repo.
        """
        if env is None:
            load_dotenv()
        source = os.environ if env is None else env
        uri = source.get("MONGODB_URI", "")
        if not uri:
            raise IngestError(
                "MONGODB_URI is not set — add it to backend/.env (Atlas connection "
                "string, never committed)"
            )
        database = source.get("MONGODB_DB", DEFAULT_DATABASE)
        try:
            return cls(MongoClient(uri, serverSelectionTimeoutMS=10_000), database)
        except PyMongoError as exc:
            raise IngestError(f"Could not connect to Atlas: {exc.__class__.__name__}") from exc

    def _ping(self) -> None:
        try:
            self._client.admin.command("ping")
        except PyMongoError as exc:
            raise IngestError(f"Could not reach the Atlas cluster: {exc.__class__.__name__}") from exc

    def state(self) -> tuple[IngestMeta | None, int]:
        try:
            doc = self._collection.find_one({}, {"embedding_model": 1, "dim": 1})
            count = self._collection.count_documents({})
        except PyMongoError as exc:
            raise IngestError(f"Could not read the chunks collection: {exc.__class__.__name__}") from exc
        if doc is None or count == 0:
            return None, 0
        try:
            return IngestMeta(doc["embedding_model"], doc["dim"]), count
        except (KeyError, TypeError) as exc:
            raise IngestError(
                "Stored Chunks are missing embedding metadata — the collection is "
                "corrupt; drop it and re-run the ingest"
            ) from exc

    def reset(self) -> None:
        """Drop the collection — its vector index goes with it: nothing survives."""
        try:
            self._collection.drop()
        except PyMongoError as exc:
            raise IngestError(f"Could not reset the collection: {exc.__class__.__name__}") from exc

    def replace_documents(self, docs: Sequence[Mapping[str, object]]) -> None:
        # Known trade-off: delete-then-insert is not atomic (M0 free tier has no
        # multi-document transactions). A mid-insert failure leaves a partial
        # corpus, but it self-heals: the next run's chunk-count check sees the
        # store as changed and re-embeds, and state() refuses to skip over a
        # metadata-less document.
        try:
            self._collection.delete_many({})
            if docs:
                self._collection.insert_many(list(docs), ordered=False)
        except PyMongoError as exc:
            raise IngestError(f"Could not store the chunks: {exc.__class__.__name__}") from exc

    def ensure_index(self, definition: Mapping[str, object]) -> None:
        """Create or update the one vector index, then wait until it is queryable.

        An index with the right name but a stale definition (different dim or
        similarity, left by an older run or hand-made in the UI) is updated, not
        silently accepted.
        """
        try:
            stored_definition = self._index_definition()
            if stored_definition is None:
                self._collection.create_search_index(
                    SearchIndexModel(
                        definition=dict(definition),
                        name=self._index_name,
                        type="vectorSearch",
                    )
                )
            elif stored_definition != dict(definition):
                self._collection.update_search_index(
                    name=self._index_name, definition=dict(definition)
                )
            self._wait_until_ready()
        except PyMongoError as exc:
            raise IngestError(f"Could not create the vector index: {exc.__class__.__name__}") from exc

    def search(self, vector: Sequence[float], k: int) -> list[dict[str, object]]:
        """Top-k Chunks by cosine similarity via the ``$vectorSearch`` stage."""
        pipeline = [
            {
                "$vectorSearch": {
                    "index": self._index_name,
                    "path": "embedding",
                    "queryVector": list(vector),
                    "numCandidates": max(50, k * 20),
                    "limit": k,
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "text": 1,
                    "source": 1,
                    "page": 1,
                    "chunk_index": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        try:
            return list(self._collection.aggregate(pipeline))
        except PyMongoError as exc:
            raise IngestError(f"Vector search failed: {exc.__class__.__name__}") from exc

    def _index_definition(self) -> dict[str, object] | None:
        """The stored definition of our index, or None when it does not exist."""
        for idx in self._collection.list_search_indexes():
            if idx.get("name") == self._index_name:
                definition = idx.get("latestDefinition") or idx.get("definition")
                return dict(definition) if definition is not None else {}
        return None

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + _INDEX_READY_TIMEOUT_S
        while time.monotonic() < deadline:
            for idx in self._collection.list_search_indexes():
                if idx.get("name") == self._index_name and idx.get("status") == "READY":
                    return
            time.sleep(_INDEX_POLL_INTERVAL_S)
        raise IngestError(
            f"Vector index {self._index_name!r} was not READY within "
            f"{_INDEX_READY_TIMEOUT_S}s"
        )