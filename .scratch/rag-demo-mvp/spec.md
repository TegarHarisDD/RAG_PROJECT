Status: ready-for-agent

# Spec: RAG Portfolio Demo — MVP

## Problem Statement

A job seeker needs a live, public way to demonstrate end-to-end RAG engineering skills to recruiters and reviewing engineers. Resumes and notebooks don't prove that a system actually works: visitors can't type a question into a notebook and see a streamed, cited answer appear. Without a running demo, the owner's retrieval, generation, evaluation, and deployment work is invisible exactly when it matters — while someone decides whether to interview them.

## Solution

A public web app where anyone types a question about a fixed document set (the Corpus) and watches an answer stream in, with the exact Document, page, and Chunk text it came from shown as expandable Citations. If the answer isn't in the Corpus, the app says so honestly (a Refusal) instead of making something up. The whole system runs on free tiers and free models — zero running cost — and the codebase is small, typed, and documented so an engineer can read it in ten minutes and see every layer: ingestion, retrieval, generation, evaluation, deployment.

## User Stories

### Asking and answering

1. As a visitor, I want to type a Question and see the answer stream in token by token, so that the demo feels alive instead of hanging silently.
2. As a visitor, I want the answer to draw only from the Corpus, so that I can trust what I read.
3. As a visitor, I want to see which Document, page, and Chunk each answer drew from, so that I can verify the answer myself.
4. As a visitor, I want Citations as expandable cards showing the verbatim Chunk text, so that I can inspect the evidence without leaving the page.
5. As a visitor, I want a clear "I couldn't find that in the documents" message when the Corpus doesn't cover my question, so that I'm never misled by a confident-sounding guess.
6. As a visitor, I want to click an example Question and have it asked instantly, so that I can try the demo with zero effort.
7. As a visitor, I want my conversation history kept for the session (in the browser only), so that I can ask follow-ups without an account.
8. As a visitor, I want a visible loading state when the server is waking up or retrieving, so that waiting is never a blank screen.
9. As a visitor, I want a clear error message with a retry button when the answer fails (rate limit, provider down), so that a failure looks handled, not broken.
10. As a visitor, I want to see which corpus the demo answers from and its license attribution, so that I know the scope before asking.
11. As a visitor, I want to know the demo's limits (fixed Corpus, no uploads), so that my expectations match reality.
12. As a visitor on a phone, I want the chat UI usable on a small screen, so that I can try it wherever I am.
13. As a visitor who prefers dark interfaces, I want a dark mode, so that the demo is comfortable to use.
14. As a visitor, I want the server-sent stream to end cleanly with the Citations payload, so that answers and evidence always arrive together.

### Reviewing (recruiter / engineer)

15. As a recruiter, I want to see a working AI system in under a minute of visiting, so that I can form a judgment quickly.
16. As a reviewing engineer, I want a README with an architecture diagram, design decisions, evaluation results, and limitations, so that I can understand the system in ten minutes.
17. As a reviewing engineer, I want provider calls wrapped behind thin functions, so that I can see how to swap models without reading the whole codebase.
18. As a reviewing engineer, I want the model IDs in configuration rather than hardcoded, so that I can see the system survives provider churn.
19. As a reviewing engineer, I want the Eval Set and its results table in the README, so that I can see quality was measured, not claimed.
20. As a reviewing engineer, I want tests that exercise the API with faked providers, so that I can see the behavior contract without network dependencies.
21. As a reviewing engineer, I want ADRs recording the non-obvious choices, so that I don't misread deliberate decisions as mistakes.

### Operating (owner)

22. As the owner, I want per-IP rate limiting and a Question length cap, so that strangers can't exhaust the free-model quota before a recruiter visits.
23. As the owner, I want a global daily stop under the provider's free cap, so that the day's quota always has headroom for a real visitor.
24. As the owner, I want API keys only on the backend, so that no secret reaches the browser or the repo.
25. As the owner, I want a fallback chain of free LLM models tried in order, so that one model rotating away doesn't take the demo down.
26. As the owner, I want a one-off ingestion script that parses the PDF, chunks it, embeds the Chunks in batches, and stores them with full metadata, so that the pipeline is reproducible end to end.
27. As the owner, I want `embedding_model` and `dim` stored on every Chunk, so that changing embedding models means a clean re-ingest, never a silent mix.
28. As the owner, I want a health endpoint for hosting checks, so that the platform's monitoring works.
29. As the owner, I want graceful degradation when OpenRouter or MongoDB is unreachable, so that the demo fails visibly and politely, not with a stack trace.
30. As the owner, I want a working `rag.py` I can exercise from the CLI, so that I can debug retrieval and generation without the UI.
31. As the owner, I want the Eval Set draft generated for me to review and correct, so that final editorial control stays mine.
32. As the owner, I want deterministic eval scoring (expected keywords + citation page match) plus my own review of misses, so that results are reproducible and honest.

## Implementation Decisions

- **Stack**: React + Vite + Tailwind in TypeScript (frontend); FastAPI with Pydantic models (backend); MongoDB Atlas free cluster with Atlas Vector Search; OpenRouter for both embeddings and the LLM. FastAPI is confirmed over Django (from the original PRD's open questions).
- **Corpus**: Regulation (EU) 2024/1689 (the EU AI Act), original Official Journal PDF (144 pages), regulation body Articles 1–~113 only, annexes excluded. Attribution on the landing page: official EU publication, CC BY 4.0 / reusable per Decision 2011/833/EU.
- **Data model**: a `chunks` collection — one document per Chunk with text, embedding vector, source, page, chunk_index, embedding_model, dim (per ADR-0002).
- **Ingestion**: one-off script; PDF parsing with pypdf (BSD license); ~500-token Chunks with ~80-token overlap; embeddings requested in batched array calls to the free embedding model `liquid/lfm-2.5-embedding-350m:free` (1024 dims) — a few dozen requests, inside the free daily cap; ingest must handle drop-and-recreate of the vector index when model/dim change.
- **Retrieval**: Atlas vector search, top-k = 4 defaults; tuned only if the Eval Set shows a problem.
- **Generation**: Prompt assembled as system rules (answer only from context; cite Document+page; Refuse when the Chunks don't support an answer), the Question, and the retrieved Chunks; low temperature.
- **Model strategy** (per ADR-0001): strictly free models, IDs in a config-ordered fallback chain — `qwen/qwen3.8-27b:free` → `google/gemma-4-31b-it:free` → `nvidia/nemotron-3-super-120b-a12b:free`; embedding model likewise a config value. Chain is tried in order; all-free variants share one account-wide daily counter (20 req/min, 50 req/day), which application limits sit under.
- **Abuse protection**: 5 Questions/hour/IP, 500-character max Question length, ~40/day global stop; enforced in the FastAPI layer.
- **API contract**: `POST /ask` streams answer tokens as Server-Sent Events and terminates with a Citations payload (Document, page, verbatim Chunk text); `GET /health` for hosting checks.
- **Frontend**: session-only chat history in the browser; streaming text; expandable Citation cards; 3–5 example Questions; loading/"server waking up" state; error + retry state; dark mode toggle; landing page states the Corpus and its attribution.
- **Hosting**: frontend on Vercel (hobby), backend on Render (free tier, ~1 min cold start after 15 min idle — the UI communicates it); default URLs, no custom domain.
- **Security/privacy**: API keys only in backend environment; Corpus is a public EU document, so chunk text leaving the process to third-party APIs is acceptable and stated in the README.
- **ADRs recorded**: 0001 (strictly-free model strategy with config fallback chain), 0002 (Atlas M0 + per-chunk embedding metadata enabling swap-by-re-ingest).

## Testing Decisions

- **What makes a good test here**: tests assert external behavior — the HTTP contract, streamed output shape, status/error paths — never implementation internals. No test should call OpenRouter or Atlas for real.
- **Primary seam**: the API seam. The FastAPI app is tested with fake `embed()` and `generate()` implementations injected behind the thin provider wrappers, exercising rate limiting, retrieval orchestration, Prompt assembly, SSE streaming, Citations payload, and Refusal behavior end to end — no network.
- **Provider seam**: the thin `embed()`/`generate()` wrappers get smoke-level tests only (request construction, error mapping on non-2xx), with real HTTP mocked.
- **Pure functions**: chunking (token counts, overlap, page mapping) and the eval scorer (keyword matching, citation page match) are pure and unit-tested directly at their own boundary.
- **Eval Set**: ~50 Eval Questions (≈40 in-scope, 10 out-of-scope), drafted from the Corpus for the owner to review; the scorer checks expected keywords in answers and citation page matches, flags Refusal correctness on out-of-scope Questions; misses get human review. Results land in the README table. The eval harness is a script, not a test suite.
- **Prior art**: none — greenfield; this spec establishes the testing conventions.

## Out of Scope

- User accounts, login, per-user data, or chat history beyond the session
- User document uploads; the Corpus is fixed at build time
- Hybrid search, reranker, feedback thumbs, model selector — all post-MVP (README future work)
- Multi-tenant scale, high availability, observability beyond logs
- Fine-tuning or training any model
- Paid model usage or credit purchases of any kind in the MVP
- Custom domain

## Further Notes

- Free `:free` model variants rotate frequently; the fallback chain is designed to be edited in config when models disappear. Verify model IDs and embedding dimensions empirically at ingestion time before fixing the Atlas index size.
- The embeddings endpoint accepts batched arrays of strings; an undocumented payload ceiling exists (HTTP 413), so batch sizes start conservative.
- Atlas free-tier limits to respect: max 3 search/vector indexes combined, 512 MB storage, ≤8,192 embedding dims — one vector index and a small Corpus fit easily.
- Backend free tier sleeps after 15 min idle with ~1 min cold start; the UI's "waking up" state is a first-class requirement, not polish.
- Original PRD open questions are all resolved: corpus (EU AI Act), FastAPI confirmed, models chosen (all-free), budget ($0), hosting (default URLs).
