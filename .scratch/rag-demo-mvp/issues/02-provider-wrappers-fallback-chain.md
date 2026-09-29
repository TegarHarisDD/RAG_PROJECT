# 02: Provider wrappers + config + model fallback chain

**What to build:** Thin `embed()` and `generate()` functions wrap every OpenRouter call, with all model IDs (the free embedding model and the free LLM fallback chain) living in configuration. From the CLI you can embed a string and generate from a Prompt, and when a model in the chain fails or no longer exists, the chain tries the next one in order. This is the only place real OpenRouter HTTP is spoken.

**Blocked by:** 01 (project skeleton + health endpoint).

**Status:** resolved

- [x] `embed()` accepts a batch of texts and returns vectors; `generate()` streams tokens from a Prompt
- [x] Embedding model ID and LLM fallback chain live in config, not hardcoded anywhere
- [x] Fallback chain tries models in config order; a missing/rate-limited model moves to the next gracefully
- [x] All-free model IDs configured per spec: free embedding model (1024 dims) and the three-model free LLM chain
- [x] Provider errors map to clean exceptions; no stack traces or raw HTTP leak upward
- [x] Smoke-level tests for request construction and error mapping (HTTP mocked, no real calls)
- [x] Verifiable from CLI: embed a string, generate from a Prompt, see the chain try models in order

## Comments

- Implemented as `app/config.py` (model IDs + base URL, env-overridable, spec defaults) and `app/providers.py` (`embed`, `generate`, `ProviderError`/`EmbeddingError`/`GenerationError`). `generate` walks the chain in config order; any non-2xx or connection failure moves to the next model, and exhausting the chain raises one clean `GenerationError` naming each failure. An `on_attempt` callback lets the CLI (`python -m app.cli`) print each chain attempt to stderr.
- Tests: 9 passing — config pinning against the spec's free model IDs, `embed` request construction + error mapping, `generate` streaming, fallback order (429 → 404 → success), all-fail error. HTTP mocked with `httpx.MockTransport`, no real calls.
- CLI verified for the no-key path (`error: OPENROUTER_API_KEY is not set`, exit 1); live OpenRouter verification needs a real key in `backend/.env`.
- Code-review fixes: `load_dotenv()` moved into `load_provider_config()` so the CLI (not just the API) sees `backend/.env`; a mid-answer stream break now raises `GenerationError` instead of splicing the next model's answer onto the partial one; in-stream error events and usage-only SSE chunks no longer crash with raw `KeyError`/`JSONDecodeError`; a malformed HTTP 200 embedding response maps to a clean `EmbeddingError`; a blank `LLM_MODELS` value restores the default chain instead of yielding an empty one. 14 tests passing, mypy clean.
- Still pending (by design): the default model IDs in config match the spec but have never been verified against OpenRouter live — that check happens empirically at ingestion time (ticket 04, per spec Further Notes) and needs a real `OPENROUTER_API_KEY`. The chain is designed to survive a rotated default.
