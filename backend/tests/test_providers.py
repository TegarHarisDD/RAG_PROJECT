"""Provider seam: OpenRouter HTTP mocked, request construction and error mapping."""
import json
from collections.abc import Iterator

import httpx
import pytest

from app.config import ProviderConfig
from app.providers import EmbeddingError, GenerationError, embed, generate

TEST_CONFIG = ProviderConfig(
    openrouter_api_key="test-key",
    openrouter_base_url="https://openrouter.ai/api/v1",
    embedding_model="test-embedder:free",
    llm_models=("model-a:free", "model-b:free", "model-c:free"),
)


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def capture_handler(captured: dict, response: httpx.Response):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return response

    return handler


def test_embed_sends_batched_texts_and_returns_vectors() -> None:
    """A batch of texts goes out as one array request; vectors come back in order."""
    captured: dict = {}
    vectors = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
    response = httpx.Response(
        200, json={"data": [{"embedding": v} for v in vectors]}
    )

    result = embed(
        ["a", "b", "c"],
        config=TEST_CONFIG,
        client=mock_client(capture_handler(captured, response)),
    )

    assert result == vectors
    assert captured["url"] == "https://openrouter.ai/api/v1/embeddings"
    assert captured["headers"]["authorization"] == "Bearer test-key"
    assert captured["body"] == {"model": "test-embedder:free", "input": ["a", "b", "c"]}


def test_embed_maps_provider_errors_to_clean_exceptions() -> None:
    """A non-2xx response surfaces as a readable error — no raw HTTP body leaks."""
    captured: dict = {}
    response = httpx.Response(
        413,
        json={"error": {"message": "Input too large"}},
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/embeddings"),
    )

    with pytest.raises(EmbeddingError) as exc_info:
        embed(
            ["a"],
            config=TEST_CONFIG,
            client=mock_client(capture_handler(captured, response)),
        )

    message = str(exc_info.value)
    assert "Input too large" in message
    assert "HTTP 413" in message
    assert "Traceback" not in message
    assert '"input"' not in message  # no raw request/response JSON leaks upward


def sse_response(chunks: list[str]) -> httpx.Response:
    """An OpenRouter-style SSE stream yielding the given content chunks."""
    lines = [
        f'data: {json.dumps({"choices": [{"delta": {"content": chunk}}]})}\n\n'
        for chunk in chunks
    ]
    lines.append("data: [DONE]\n\n")
    return httpx.Response(200, content=iter(line.encode() for line in lines))


def test_generate_streams_tokens_from_the_first_chain_model() -> None:
    """Tokens stream in order from the first configured model via SSE."""
    captured: dict = {}

    tokens = list(
        generate(
            "What is the AI Act?",
            config=TEST_CONFIG,
            client=mock_client(capture_handler(captured, sse_response(["Hello", " world"]))),
        )
    )

    assert tokens == ["Hello", " world"]
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer test-key"
    assert captured["body"] == {
        "model": "model-a:free",
        "stream": True,
        "messages": [{"role": "user", "content": "What is the AI Act?"}],
    }


def test_generate_falls_back_to_next_model_when_one_fails() -> None:
    """A rate-limited or missing model moves the chain to the next entry, in order."""
    attempted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        attempted.append(model)
        if model == "model-a:free":
            return httpx.Response(429, json={"error": {"message": "Rate limit exceeded"}})
        if model == "model-b:free":
            return httpx.Response(404, json={"error": {"message": "No endpoints found"}})
        return sse_response(["From model c"])

    tokens = list(
        generate("Question?", config=TEST_CONFIG, client=mock_client(handler),
                 on_attempt=lambda model, reason: None)
    )

    assert tokens == ["From model c"]
    assert attempted == ["model-a:free", "model-b:free", "model-c:free"]


def test_generate_raises_clean_error_when_every_model_fails() -> None:
    """Exhausting the chain raises one readable error naming each model's failure."""
    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        return httpx.Response(429, json={"error": {"message": "Rate limit exceeded"}})

    with pytest.raises(GenerationError) as exc_info:
        list(generate("Question?", config=TEST_CONFIG, client=mock_client(handler)))

    message = str(exc_info.value)
    assert "model-a:free" in message and "model-b:free" in message
    assert "Rate limit exceeded" in message
    assert "Traceback" not in message


def test_generate_does_not_fall_back_after_tokens_were_streamed() -> None:
    """A mid-answer drop fails loudly instead of splicing a second model's answer on."""
    def dropping_stream() -> Iterator[bytes]:
        yield f'data: {json.dumps({"choices": [{"delta": {"content": "The AI Act is"}}]})}\n\n'.encode()
        raise httpx.ReadError("connection dropped")

    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["model"] == "model-a:free":
            return httpx.Response(200, content=dropping_stream())
        return sse_response(["a complete answer from model b"])

    with pytest.raises(GenerationError):
        list(generate("Question?", config=TEST_CONFIG, client=mock_client(handler)))


def test_generate_surfaces_in_stream_error_events_cleanly() -> None:
    """An in-stream provider error event becomes a clean error, not a raw KeyError."""
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.dumps({"error": {"message": "upstream model error"}})
        return httpx.Response(200, content=iter([f"data: {payload}\n\n".encode()]))

    with pytest.raises(GenerationError) as exc_info:
        list(generate("Question?", config=TEST_CONFIG, client=mock_client(handler)))

    assert "upstream model error" in str(exc_info.value)


def test_generate_skips_bookkeeping_chunks_and_falls_back_on_early_errors() -> None:
    """Usage-only chunks (empty choices) are skipped; a pre-answer error tries the next model."""
    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["model"] == "model-a:free":
            lines = [
                json.dumps({"usage": {"total_tokens": 3}, "choices": []}),
                json.dumps({"error": {"message": "overloaded"}}),
            ]
            return httpx.Response(
                200, content=iter((f"data: {line}\n\n").encode() for line in lines)
            )
        return sse_response(["From model b"])

    tokens = list(generate("Question?", config=TEST_CONFIG, client=mock_client(handler)))

    assert tokens == ["From model b"]


def test_embed_maps_malformed_success_responses_to_clean_errors() -> None:
    """An HTTP 200 with an unexpected body surfaces as a clean error, no body leak."""
    for body in ('<html>gateway error</html>', '{"data": [{}]}'):
        response = httpx.Response(200, text=body)

        with pytest.raises(EmbeddingError) as exc_info:
            embed(["a"], config=TEST_CONFIG, client=mock_client(lambda request, b=body: response))

        message = str(exc_info.value)
        assert body not in message
        assert "Traceback" not in message
