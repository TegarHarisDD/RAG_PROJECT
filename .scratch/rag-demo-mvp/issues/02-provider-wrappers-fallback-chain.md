# 02: Provider wrappers + config + model fallback chain

**What to build:** Thin `embed()` and `generate()` functions wrap every OpenRouter call, with all model IDs (the free embedding model and the free LLM fallback chain) living in configuration. From the CLI you can embed a string and generate from a Prompt, and when a model in the chain fails or no longer exists, the chain tries the next one in order. This is the only place real OpenRouter HTTP is spoken.

**Blocked by:** 01 (project skeleton + health endpoint).

**Status:** ready-for-agent

- [ ] `embed()` accepts a batch of texts and returns vectors; `generate()` streams tokens from a Prompt
- [ ] Embedding model ID and LLM fallback chain live in config, not hardcoded anywhere
- [ ] Fallback chain tries models in config order; a missing/rate-limited model moves to the next gracefully
- [ ] All-free model IDs configured per spec: free embedding model (1024 dims) and the three-model free LLM chain
- [ ] Provider errors map to clean exceptions; no stack traces or raw HTTP leak upward
- [ ] Smoke-level tests for request construction and error mapping (HTTP mocked, no real calls)
- [ ] Verifiable from CLI: embed a string, generate from a Prompt, see the chain try models in order
