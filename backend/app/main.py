"""FastAPI application entry point: /health plus POST /ask (ticket 06).

The /ask contract: a Question arrives, the answer streams back as
Server-Sent Events (``token`` events), and the stream ends with a Citations
payload (Document, page, verbatim Chunk text). Refusals stream as a distinct
``refusal`` event; provider and store failures as clean ``error`` events.
Abuse limits are explicit and distinguishable — a 429 naming which limit bit,
never a generic 500.
"""
import json
import os
from collections.abc import Callable, Iterator
from dataclasses import asdict
from functools import lru_cache

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

# Backend configuration lives in .env (see .env.example); secrets never
# leave this process or get committed.
load_dotenv()

from app.abuse import AbuseLimiter, Rejection
from app.atlas import AtlasChunkStore
from app.config import (
    AbuseConfig,
    ProviderConfig,
    RetrievalConfig,
    load_abuse_config,
    load_provider_config,
    load_retrieval_config,
)
from app.ingest import ChunkStore, IngestError
from app.providers import EmbeddingError, GenerationError, ProviderError, embed, generate
from app.rag import TokenEvent, ask_stream

app = FastAPI(title="rag-portfolio-demo")

# The React frontend runs on a different origin (Vercel in prod, Vite dev
# server locally), so browser calls need CORS. Origins are env-configured,
# never hardcoded.
_FRONTEND_ORIGINS: list[str] = [
    origin.strip()
    for origin in os.environ.get("FRONTEND_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_FRONTEND_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# Loaded once at import so a malformed limit fails at startup, not per-request.
_ABUSE: AbuseConfig = load_abuse_config()

_LIMITER = AbuseLimiter(
    per_ip_per_hour=_ABUSE.questions_per_ip_per_hour,
    daily_limit=_ABUSE.daily_question_limit,
)

_ABUSE_MESSAGES: dict[str, str] = {
    "rate_limit": "Too many questions this hour — please try again later.",
    "daily_limit": "The demo has reached today's question limit. Please come back tomorrow.",
}

# The question-length cap comes from the same abuse config as the counters.
QUESTION_MAX_CHARS = _ABUSE.max_question_chars


class Question(BaseModel):
    """The request body of POST /ask."""

    text: str = Field(min_length=1, max_length=QUESTION_MAX_CHARS)


# Provider-callable shapes (the seams the tests inject fakes behind).
EmbedFn = Callable[..., list[list[float]]]
GenerateFn = Callable[..., Iterator[str]]


@lru_cache(maxsize=1)
def get_provider_config() -> ProviderConfig:
    return load_provider_config()


@lru_cache(maxsize=1)
def get_retrieval_config() -> RetrievalConfig:
    return load_retrieval_config()


def get_store_factory() -> Callable[[], ChunkStore]:
    """A store *maker*, not a store: connecting to Atlas can fail, and that
    failure must surface as a clean SSE error event — not a dependency-time
    500. The one successful connection is cached for the process's lifetime."""
    @lru_cache(maxsize=1)
    def make() -> ChunkStore:
        return AtlasChunkStore.from_env()

    return make


def get_limiter() -> AbuseLimiter:
    return _LIMITER


def get_embed_fn() -> EmbedFn:
    return embed


def get_generate_fn() -> GenerateFn:
    return generate


def _client_ip(request: Request) -> str:
    """The visitor IP for per-IP limiting.

    Render terminates TLS on a shared proxy, so ``request.client.host`` would
    be the same proxy IP for every visitor. The platform appends the real
    client to X-Forwarded-For; the last entry is the one our own proxy added —
    earlier entries are client-supplied and spoofable.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _ask_events(
    question: str,
    *,
    store_factory: Callable[[], ChunkStore],
    provider_config: ProviderConfig,
    retrieval: RetrievalConfig,
    embed_fn: EmbedFn,
    generate_fn: GenerateFn,
) -> Iterator[str]:
    """The pipeline's events mapped onto SSE, with failures mapped to clean
    ``error`` events in-band — the stream has started, so a 500 is no longer
    an honest response."""
    try:
        for event in ask_stream(
            question,
            config=provider_config,
            retrieval=retrieval,
            store=store_factory(),
            embed_fn=embed_fn,
            generate_fn=generate_fn,
        ):
            if isinstance(event, TokenEvent):
                yield _sse("token", {"text": event.text})
            elif event.answer.refused:
                yield _sse("refusal", {"message": event.answer.text})
            else:
                yield _sse(
                    "citations",
                    {"citations": [asdict(c) for c in event.answer.citations]},
                )
    except IngestError as exc:
        yield _sse("error", {"kind": "store", "message": str(exc)})
    except EmbeddingError as exc:
        yield _sse("error", {"kind": "provider", "message": str(exc)})
    except GenerationError as exc:
        yield _sse("error", {"kind": "generation", "message": str(exc)})
    except ProviderError as exc:
        yield _sse("error", {"kind": "provider", "message": str(exc)})


@app.post("/ask")
def ask_endpoint(
    question: Question,
    request: Request,
    store_factory: Callable[[], ChunkStore] = Depends(get_store_factory),
    provider_config: ProviderConfig = Depends(get_provider_config),
    retrieval: RetrievalConfig = Depends(get_retrieval_config),
    limiter: AbuseLimiter = Depends(get_limiter),
    embed_fn: EmbedFn = Depends(get_embed_fn),
    generate_fn: GenerateFn = Depends(get_generate_fn),
) -> Response:
    """Stream one cited answer as SSE.

    Events: ``token`` {"text"}, ``refusal`` {"message"}, ``citations``
    {"citations": [...]}, ``error`` {"kind", "message"}. Abuse limits are
    rejected before the stream starts with an explicit 429 naming the limit.
    """
    ip = _client_ip(request)
    rejection: Rejection | None = limiter.check(ip)
    if rejection:
        return JSONResponse(
            status_code=429,
            content={"error": rejection, "message": _ABUSE_MESSAGES[rejection]},
        )
    limiter.record(ip)  # accepted questions count, even if they fail later
    return StreamingResponse(
        _ask_events(
            question.text,
            store_factory=store_factory,
            provider_config=provider_config,
            retrieval=retrieval,
            embed_fn=embed_fn,
            generate_fn=generate_fn,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Render's proxy must not buffer the stream — tokens arrive one by one.
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Health check for hosting-platform monitoring."""
    return {"status": "ok"}