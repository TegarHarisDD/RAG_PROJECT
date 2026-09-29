# 05: Retrieval + rag.py CLI

**What to build:** The first true end-to-end answer, without any UI: a retrievable Question goes to Atlas vector search (top-k = 4), the retrieved Chunks and the Question are assembled into a Prompt, and the streaming LLM answer prints with Citations (Document, page, verbatim Chunk text) — plus an honest Refusal when the Corpus doesn't support an answer. Driven from a CLI loop for debugging without the frontend.

**Blocked by:** 04 (ingestion — Atlas setup + store Chunks).

**Status:** ready-for-agent

- [ ] Vector search returns top-k Chunks (k=4 default from config) for a Question's embedding
- [ ] Prompt assembled per spec: system rules (answer only from context, cite Document+page, Refuse when unsupported), the Question, and the retrieved Chunks; low temperature
- [ ] Streaming answer prints to the terminal; Citations (Document, page, verbatim Chunk) shown after
- [ ] Refusal surfaces honestly when the Corpus doesn't cover the Question
- [ ] CLI loop for iterative Question/answer debugging against the real pipeline
- [ ] Free LLM fallback chain applies here too (single models tried in config order)
