# 06: POST /ask streaming endpoint + abuse limits

**What to build:** The API the UI will consume: a Question arrives, the answer streams back as Server-Sent Events, and the stream ends with a Citations payload (Document, page, verbatim Chunk text). Abuse protection enforces per-IP hourly limits, Question length cap, and a global daily stop that keeps real traffic under the provider's free daily cap — the last two protect the recruiter-click experience. Provider and database failures come back as clean, mapped errors.

**Blocked by:** 05 (retrieval + rag.py CLI).

**Status:** ready-for-agent

- [ ] `POST /ask` accepts a Question and streams answer tokens as SSE
- [ ] Stream terminates with a Citations payload (Document, page, verbatim Chunk text); Refusals stream as a distinct outcome the UI can render
- [ ] Per-IP rate limit (5/hour), Question length cap (500 chars), global daily stop (~40/day) enforced
- [ ] Abuse-limit responses are explicit and distinguishable (not generic 500s)
- [ ] Provider failures (OpenRouter down / all models exhausted) and MongoDB failures map to clean error events
- [ ] API-seam tests with fake `embed()`/`generate()` cover the full contract — streaming shape, Citations payload, Refusal, rate limiting, error mapping — no network
