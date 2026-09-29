"""Thin OpenRouter wrappers: the only place real provider HTTP is spoken.

``embed()`` and ``generate()`` are the provider seam every other layer talks
to. Callers inject an ``httpx.Client`` (tests use ``httpx.MockTransport``) and
a ``ProviderConfig``, so no OpenRouter model ID or URL is hardcoded elsewhere.
All failures surface as clean ``ProviderError`` messages — never stack traces
or raw HTTP — per the graceful-degradation requirement.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence

import httpx

from app.config import ProviderConfig


class ProviderError(Exception):
    """A clean, user-facing provider failure (no stack traces leak past this)."""


class EmbeddingError(ProviderError):
    """Embedding the given texts failed on every configured attempt."""


class GenerationError(ProviderError):
    """Every model in the fallback chain failed, or the stream broke mid-answer."""


def embed(
    texts: Sequence[str],
    *,
    config: ProviderConfig,
    client: httpx.Client | None = None,
) -> list[list[float]]:
    """Embed a batch of texts with the configured model; vectors come back in order."""
    own_client = client is None
    client = client or httpx.Client()
    try:
        response = client.post(
            f"{config.openrouter_base_url}/embeddings",
            headers=_auth_headers(config),
            json={"model": config.embedding_model, "input": list(texts)},
        )
    except httpx.HTTPError as exc:
        raise EmbeddingError(f"Embedding request failed: {exc.__class__.__name__}") from exc
    finally:
        if own_client:
            client.close()

    if response.status_code != 200:
        raise EmbeddingError(
            f"Embedding model {config.embedding_model!r} failed: {_failure_reason(response)}"
        )

    try:
        return [item["embedding"] for item in response.json()["data"]]
    except (ValueError, KeyError, TypeError):
        raise EmbeddingError(
            f"Embedding model {config.embedding_model!r} returned a response "
            "with an unexpected shape"
        ) from None


def generate(
    prompt: str,
    *,
    config: ProviderConfig,
    client: httpx.Client | None = None,
    on_attempt: Callable[[str, str | None], None] | None = None,
    temperature: float | None = None,
) -> Iterator[str]:
    """Stream tokens from the first chain model that answers.

    Models are tried in ``config.llm_models`` order (ADR-0001): a missing or
    rate-limited model moves the chain to the next one. ``on_attempt`` is
    called with ``(model, None)`` when a model starts answering and with
    ``(model, reason)`` for each failure, so callers (e.g. the CLI) can show
    the chain working. ``temperature`` lands in the request only when given,
    keeping plain generation on its original wire shape. If every model fails,
    a single clean ``GenerationError`` summarizing the per-model reasons is
    raised.
    """
    own_client = client is None
    client = client or httpx.Client()
    failures: list[str] = []
    yielded = False
    try:
        for model in config.llm_models:
            reason: str | None = None
            try:
                with client.stream(
                    "POST",
                    f"{config.openrouter_base_url}/chat/completions",
                    headers=_auth_headers(config),
                    json={
                        "model": model,
                        "stream": True,
                        "messages": [{"role": "user", "content": prompt}],
                        **({"temperature": temperature} if temperature is not None else {}),
                    },
                ) as response:
                    if response.status_code != 200:
                        response.read()
                        reason = _failure_reason(response)
                    else:
                        if on_attempt:
                            on_attempt(model, None)
                        for token in _iter_sse_tokens(response):
                            yielded = True
                            yield token
                        return
            except httpx.HTTPError:
                reason = "connection failed"
                if yielded:
                    # Partial answer already sent; a second model would splice
                    # its answer onto it, so fail loudly instead.
                    raise GenerationError(
                        "The answer stream broke mid-answer. Please retry the question."
                    ) from None
            except GenerationError as exc:
                reason = str(exc)
                if yielded:  # error event after tokens were sent — terminal
                    raise
            if on_attempt:
                on_attempt(model, reason)
            failures.append(f"{model}: {reason}")
    finally:
        if own_client:
            client.close()

    raise GenerationError(
        "All fallback models failed: " + "; ".join(failures)
    )


def _iter_sse_tokens(response: httpx.Response) -> Iterator[str]:
    """Yield content tokens from an OpenRouter SSE stream.

    OpenRouter interleaves non-token events (usage chunks with empty
    ``choices``, in-stream ``{"error": ...}`` objects); these map to skips and
    a clean ``GenerationError`` respectively, never a raw parse crash.
    """
    for line in response.iter_lines():
        if not line.startswith("data: "):
            continue
        data = line[len("data: "):]
        if data.strip() == "[DONE]":
            return
        try:
            payload = json.loads(data)
        except ValueError:
            continue
        if "error" in payload:
            message = payload["error"].get("message", "provider stream error")
            raise GenerationError(f"Generation failed: {message}")
        choices = payload.get("choices") or []
        if not choices:
            continue
        content = choices[0].get("delta", {}).get("content")
        if content:
            yield content


def _auth_headers(config: ProviderConfig) -> dict[str, str]:
    if not config.openrouter_api_key:
        raise ProviderError("OPENROUTER_API_KEY is not set")
    return {"Authorization": f"Bearer {config.openrouter_api_key}"}


def _failure_reason(response: httpx.Response) -> str:
    """A short human-readable reason from a non-2xx response — no raw HTTP dump."""
    try:
        message = response.json()["error"]["message"]
    except Exception:
        return f"HTTP {response.status_code}"
    return f"{message} (HTTP {response.status_code})"
