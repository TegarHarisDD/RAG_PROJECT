# rag-portfolio-demo

A public RAG portfolio demo: ask questions about a fixed document set and get
streamed answers with citations. If the documents don't contain the answer, it
says so instead of guessing.

**Live demo:** _deployed URLs land with ticket 09 (Vercel + Render, free
tiers). Until then, run it locally (below)._

The Corpus is **Regulation (EU) 2024/1689** — the EU AI Act — as the authentic
Official Journal English PDF (144 pages, regulation body only, annexes
excluded). It is a public EU document, reusable under the EU's reuse policy
(Decision 2011/833/EU). Asking a question sends the retrieved document text to
free third-party model APIs (OpenRouter); nothing else is collected.

## What a reviewing engineer will find

Every layer is small, typed, and readable in one sitting:

- **Ingestion** — one-off script: PDF → pages → ~500-token Chunks with ~80-token
  overlap → batched embeddings → MongoDB Atlas with a vector index
  (`backend/app/chunker.py`, `backend/app/ingest.py`).
- **Retrieval + generation** — embed the Question, pull top-k Chunks, assemble
  the Prompt, stream the answer through a fallback chain of free models
  (`backend/app/rag.py`, `backend/app/providers.py`).
- **API** — `POST /ask` streams Server-Sent Events (`token` → `citations`, or a
  distinct `refusal` event), with per-IP and daily abuse limits under the free
  provider caps (`backend/app/main.py`, `backend/app/abuse.py`).
- **UI** — React + Vite + Tailwind: streamed text, expandable citation cards,
  refusal and error/retry states, dark mode, session-only history
  (`frontend/src/`).
- **Evaluation** — a 50-question Eval Set, a deterministic scorer, and a
  harness script that runs the Set against the live pipeline
  (`backend/app/eval_scorer.py`, `backend/evals/`).

Testing is at the seams (spec's Testing Decisions): the FastAPI app is tested
end to end with fake `embed()`/`generate()` behind the provider wrappers — no
test touches OpenRouter or Atlas. The chunker and the eval scorer are pure
functions unit-tested directly. `cd backend && python -m pytest` runs the
suite; `python -m mypy app tests evals` type-checks it.

## Running locally

**Backend** (Python 3.10+, FastAPI):

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in real values; .env is git-ignored, never committed
python -m app.ingest ../corpus/eu-ai-act.pdf   # one-off: parse, chunk, embed, store
uvicorn app.main:app --reload
```

**Frontend** (Node 22+, React + Vite + Tailwind):

```bash
cd frontend
npm install
npm run dev
```

The frontend dev server runs on `http://localhost:5173`; the backend API on
`http://localhost:8000` with `GET /health` for platform checks. To exercise
retrieval without the UI:

```bash
cd backend
python -m app.cli ask "Which AI practices are prohibited?"   # one-shot, streamed
python -m app.cli ask                                        # interactive debug loop
```

## Architecture

```mermaid<br>flowchart LR<br>    subgraph browser [Browser]<br>        UI[React chat UI\nstreamed text, citation cards,\nrefusal / error / retry states]<br>    end<br>    subgraph backend [FastAPI backend]<br>        API["POST /ask (SSE)\n+ abuse limits (per-IP / daily)"]<br>        RAG["rag pipeline\nretrieve → prompt → stream"]<br>        PROV["provider wrappers\nembed() / generate()"]<br>        CHAIN["OpenRouter fallback chain\nfree models, config-ordered (ADR-0001)"]<br>    end<br>    subgraph storage [MongoDB Atlas M0]<br>        VS[("chunks collection\nvectors + text + page +\nembedding_model + dim (ADR-0002)\nvector search index")]<br>    end<br><br>    UI -->|Question| API<br>    API --> RAG<br>    RAG -->|embed Question| PROV --> CHAIN<br>    RAG -->|top-k Chunks| VS<br>    RAG -->|Prompt + Chunks| PROV<br>    PROV -->|answer tokens| RAG<br>    API -->|SSE: token* → citations / refusal / error| UI<br>```

One turn: the Question is embedded, Atlas Vector Search returns the top-4
Chunks, the Prompt (system rules + Question + verbatim Chunks) goes to the
first free model in the fallback chain, and the answer streams back token by
token, ending with the Citations payload (Document, page, verbatim Chunk
text). When the Chunks don't support an answer, the stream ends in a Refusal —
an eval pass, not a failure.

## Design decisions

The non-obvious choices are recorded as ADRs:

- **[ADR-0001](docs/adr/0001-strictly-free-model-strategy.md) — strictly-free
  model strategy with a config fallback chain.** All model IDs are
  env-configured and tried in order; free variants rotate, so swapping one is
  a `.env` edit. Application limits (5 questions/hour/IP, 500-char cap,
  ~40/day global stop) sit under the provider's free daily cap so a real
  visitor always has quota.
- **[ADR-0002](docs/adr/0002-atlas-m0-with-per-chunk-embedding-metadata.md) —
  Atlas M0 with per-chunk embedding metadata.** Every Chunk stores
  `embedding_model` and `dim`, so changing embedding models means a clean
  drop-and-reingest, never a silent mix of incompatible vectors.

Other deliberate choices, briefly:

- **SSE with a terminal payload.** The stream ends with the Citations payload,
  so answers and evidence always arrive together (spec user story 14). Refusals
  are a distinct event type, not an answer shaped like one.
- **Refusal-first retrieval.** If retrieval finds nothing, the Refusal is
  returned without calling the LLM — the shared free daily cap is never spent
  on a Question the Corpus cannot answer.
- **Chunks are the citation unit.** Chunk text is stored normalized (single
  spaces) and shown verbatim in citation cards; a Chunk's page is where its
  text starts, and windowing keeps ~80 tokens of overlap so boundary claims
  stay retrievable.
- **3 chars/token, not 4.** The free embedding model tokenizes denser than the
  4:1 heuristic (>10% overshoot measured on the Corpus), and its hard
  512-token ceiling truncated Chunks; the chunker's estimate leaves headroom.
- **Eval scoring is deterministic.** No LLM-judge: expected-keyword matching,
  citation page matching, and Refusal correctness are pure functions, so the
  numbers are reproducible and every miss is inspectable by the owner.

## Evaluation

The **Eval Set** (`backend/evals/eval_set.json`) holds 50 Eval Questions:
40 in-scope (drawn from the Corpus, each with expected answer keywords and the
page a correct citation must hit) and 10 out-of-scope (general knowledge,
cooking, weather, poetry, GDPR, a comparison with US law, and one deliberate
boundary case — the annexes are excluded from the Corpus, so asking for Annex
III's contents must produce a Refusal). The Set was drafted for the owner's
review; final wording stays theirs. A few examples, in the Set's own words:

- _in-scope:_ "Which AI practices are prohibited outright by the AI Act?"
- _in-scope:_ "What is a GPAI model with systemic risk, and what extra
  obligations come with that label?"
- _out-of-scope:_ "How do I feed and maintain a sourdough starter?"
- _out-of-scope (boundary):_ "List the high-risk systems named in Annex III."

The **scorer** (`backend/app/eval_scorer.py`) is deterministic: every expected
keyword must appear in the answer (case/punctuation-insensitive token
matching), at least one cited page must be among the expected pages, and
out-of-scope Questions must produce the Refusal. An in-scope Question answered
with a Refusal counts as a miss. No LLM judges the answers.

The **harness** (`backend/evals/run_eval.py`) is a script, not part of the test
suite — each Question costs two real provider calls, and the free-tier daily
cap cannot cover the full Set in one session, so results are cached and runs
resume across sessions:

```bash
cd backend
python -m evals.run_eval            # run (or resume) the full Set
python -m evals.run_eval --limit 5  # spend a little quota, stop after 5
python -m evals.run_eval --fresh    # ignore cached results, redo everything
```

### Results

Run against the live pipeline (Atlas Vector Search + OpenRouter free models) —
42/50 passed, 0 errors:

- **In-scope: 33/40 passed** — expected keywords present, a citation page
  matches, no Refusal.
- **Out-of-scope: 9/10 correctly refused.** The one miss (`ai-haiku`) asked for
  a poem; the model played along instead of refusing — exactly the failure
  mode the refusal rule exists for, kept in the Set so it stays measured.

<details>
<summary>The 7 in-scope misses (each is a real defect or retrieval gap)</summary>

| Question | What happened |
| --- | --- |
| `penalties-prohibited` | **Wrong answer**: reported the EUR 1,500,000 fine for false information (p. 117) instead of the EUR 35M / 7% fine for prohibited practices (p. 115) — retrieval never surfaced Article 99(3). |
| `entry-into-force` | **Wrong answer**: conflated the entry-into-force and application dates, retrieving recitals instead of the final article (p. 123). |
| `deployer-obligations` | Retrieval surfaced Articles 13/24-25 (provider-side) and missed Article 26 (deployer obligations, p. 67); the answer drifted to the wrong articles. |
| `prohibited-overview` | Listed the prohibited practices but omitted social scoring — the retrieved excerpt cut off before item (c), and the answer says so honestly. |
| `corrective-actions` | Cited the general obligation list (Article 16(j), p. 62) but omitted the actual Article 20 duties (bring into conformity, withdraw, recall). |
| `authorised-representative` | Named the duty but omitted the "written mandate" element of Article 22. |
| `fria` | Named private providers of public services but omitted bodies governed by public law — half the Article 27 list. |

</details>

<details>
<summary>Full results table (50 questions)</summary>

| Question | Scope | Verdict | Missing keywords | Cited pages | Expected pages |
| --- | --- | --- | --- | --- | --- |
| 1. purpose | in | PASS | — | 44, 1, 45, 2 | 44 |
| 2. ai-system-definition | in | PASS | — | 46, 46, 4, 14 | 46 |
| 3. provider-definition | in | PASS | — | 46, 24, 66, 64 | 46 |
| 4. deployer-definition | in | PASS | — | 46, 66, 67, 4 | 46 |
| 5. deep-fake-definition | in | PASS | — | 82, 50, 34, 46 | 50 |
| 6. gpai-model-definition | in | PASS | — | 26, 26, 27, 26 | 26, 50 |
| 7. ai-literacy | in | PASS | — | 6, 82, 24, 6 | 6, 50 |
| 8. prohibited-overview | in | FAIL | social scoring | 51, 6, 46, 82 | 51 |
| 9. manipulation-prohibition | in | PASS | — | 8, 51, 12, 46 | 51, 8 |
| 10. vulnerable-exploitation | in | PASS | — | 33, 8, 55, 51 | 51 |
| 11. social-scoring | in | PASS | — | 9, 16, 33, 51 | 51, 9 |
| 12. facial-scraping | in | PASS | — | 51, 12, 12, 2 | 51, 12 |
| 13. emotion-workplace | in | PASS | — | 12, 82, 18, 46 | 12, 51 |
| 14. biometric-categorisation | in | PASS | — | 9, 51, 15, 4 | 51 |
| 15. high-risk-classification | in | PASS | — | 53, 53, 55, 107 | 53 |
| 16. profiling-high-risk | in | PASS | — | 12, 33, 16, 17 | 16, 17, 53 |
| 17. risk-management | in | PASS | — | 56, 19, 20, 56 | 56 |
| 18. data-governance | in | PASS | — | 57, 19, 57, 19 | 57 |
| 19. bias-special-data | in | PASS | — | 58, 19, 57, 19 | 57, 58 |
| 20. technical-documentation | in | PASS | — | 20, 59, 58, 55 | 58 |
| 21. log-retention | in | PASS | — | 59, 64, 20, 68 | 64 |
| 22. human-oversight | in | PASS | — | 60, 21, 20, 55 | 60 |
| 23. accuracy-robustness | in | PASS | — | 61, 21, 61, 59 | 60, 61 |
| 24. adversarial-attacks | in | PASS | — | 61, 22, 21, 61 | 61 |
| 25. corrective-actions | in | FAIL | recall | 66, 62, 66, 67 | 64 |
| 26. authorised-representative | in | FAIL | written mandate | 65, 64, 85, 85 | 64 |
| 27. deployer-obligations | in | FAIL | — | 59, 20, 62, 66 | 67 |
| 28. fria | in | FAIL | public law | 69, 25, 26, 69 | 69 |
| 29. transparency-chatbot | in | PASS | — | 33, 8, 8, 31 | 31, 33, 82 |
| 30. synthetic-marking | in | PASS | — | 34, 34, 82, 82 | 82 |
| 31. deepfake-disclosure | in | PASS | — | 34, 34, 82, 82 | 82 |
| 32. gpai-systemic | in | PASS | — | 29, 29, 83, 83 | 83 |
| 33. gpai-obligations | in | PASS | — | 26, 85, 28, 84 | 84 |
| 34. codes-of-practice | in | PASS | — | 87, 30, 44, 121 | 87 |
| 35. sandboxes | in | PASS | — | 35, 88, 88, 90 | 87, 88 |
| 36. eu-database | in | PASS | — | 33, 33, 100, 81 | 100 |
| 37. serious-incident | in | PASS | — | 101, 20, 102, 59 | 101 |
| 38. penalties-prohibited | in | FAIL | 35 000 000, whichever is higher | 51, 117, 87, 117 | 115 |
| 39. entry-into-force | in | FAIL | twentieth day, 2 August 2026 | 121, 44, 121, 87 | 123 |
| 40. phased-dates | in | PASS | — | 44, 121, 121, 87 | 44, 123 |
| 41. capital-of-australia | out | PASS | — | 95, 5, 29, 50 | refusal |
| 42. sourdough-starter | out | PASS | — | 94, 35, 35, 36 | refusal |
| 43. euro-2024-final | out | PASS | — | 120, 120, 121, 118 | refusal |
| 44. ml-framework | out | PASS | — | 35, 90, 4, 27 | refusal |
| 45. gdpr-cookies | out | PASS | — | 117, 42, 115, 117 | refusal |
| 46. brussels-weather | out | PASS | — | 36, 44, 93, 22 | refusal |
| 47. ai-haiku | out | FAIL | — | 4, 8, 33, 15 | refusal |
| 48. quantum-computing | out | PASS | — | 95, 95, 4, 50 | refusal |
| 49. us-comparison | out | PASS | — | 45, 120, 1, 6 | refusal |
| 50. annex-iii-list | out | PASS | — | 53, 53, 55, 69 | refusal |

</details>

Where expectations changed during the run: the draft's page/keyword choices
were corrected where the answer was substantively right but the draft was too
strict (e.g. answers grounded in the recitals when the draft expected only the
article page; "biases" vs "bias" singular/plural). Fails were **not** edited
away — the 8 above remain fails against the corrected draft.

### Reading the numbers honestly

- Deterministic keyword matching is strict: an answer can be substantively
  correct and still miss if it paraphrases away an expected keyword. Every
  miss is recorded with its full answer text in `backend/evals/results.json`
  for exactly that review.
- Out-of-scope Refusals depend on the free model following the Prompt's
  refusal rule; model rotation (ADR-0001) can move this number between runs.
- The harness retries transient network failures per Question, but a free-tier
  rate limit mid-run shows up as errored rows — rerun the harness the next day
  and it resumes.

## Limitations

- **Fixed Corpus.** 144-page EU AI Act PDF, regulation body only — no annexes,
  no uploads, no other documents. Questions outside it get a Refusal, and the
  landing page says so.
- **Free-tier reality.** Free models rotate and rate-limit (ADR-0001); the
  fallback chain and the UI's error/retry state absorb this, and the backend's
  ~1-minute cold start after idle is communicated as a "waking up" state.
- **Session-only history.** The conversation lives in the browser for the
  session only; no accounts, no server-side storage.
- **Retrieval is plain top-k vector search.** No hybrid search, reranker, or
  feedback loop — all post-MVP (see the spec's Out of Scope).
- **Abuse limits are in-memory.** Single-worker free tiers only; a restart
  resets the counters (errs generous, never blocks a visitor).
- **English only.** Questions are expected in English, matching the Corpus.

## Corpus attribution

`corpus/eu-ai-act.pdf` — Regulation (EU) 2024/1689 (Artificial Intelligence
Act), CELEX 32024R1689, official Official Journal English PDF. Public EU
document; reuse permitted under the EU's reuse policy (Decision
2011/833/EU). Fetched from the Publications Office cellar service
(`http://publications.europa.eu/resource/celex/32024R1689`, content
negotiation `Accept: application/pdf`); details in
[`corpus/README.md`](corpus/README.md).

## Project status
Built to the MVP spec in `.scratch/rag-demo-mvp/` (spec + tickets). Tickets
01–08 are implemented and reviewed; ticket 09 (deployment to Vercel/Render)
lands the live URLs at the top of this README.
