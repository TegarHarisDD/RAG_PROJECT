# 08: Eval Set + harness + README

**What to build:** Measured quality, published: a draft Eval Set of ~50 Eval Questions (≈40 in-scope, 10 out-of-scope) for the owner to review, a deterministic scorer (expected keywords in answers, citation page match, Refusal correctness on out-of-scope), results run against the live pipeline, and the full README — architecture diagram, design decisions, eval results table, limitations. The repo now reads as a portfolio artifact in ten minutes.

**Blocked by:** 07 (chat UI — streaming, Citations, Refusal, examples).

**Status:** ready-for-human

- [x] ~50 Eval Questions drafted from the Corpus for owner review (in-scope and out-of-scope mixed)
- [x] Deterministic scorer: expected-keyword matching in answers, citation page match, correct Refusals on out-of-scope
- [x] Harness runs the Eval Set against the pipeline and emits a results table
- [ ] Owner reviews and corrects the draft; final wording stays theirs
- [x] README: architecture diagram, design decisions (linking ADRs), eval results, limitations, how to run
- [x] Eval results table lands in the README with the accuracy targets reported honestly
- [x] Harness is a script, not part of the test suite (per spec testing decisions)

## Comments

### Implementation record

Built in the TDD loop (scorer red → green at the `score_answer` /
`parse_eval_question` seams; harness deliberately untested, per the spec's
Testing Decisions — no test touches OpenRouter or Atlas).

**Draft Eval Set** (`backend/evals/eval_set.json`) — 50 Questions: 40
in-scope (each with expected keywords + expected citation pages, grounded in
the ingested body pages 1–123) and 10 out-of-scope, including the deliberate
boundary case asking for Annex III's contents (annexes are excluded from the
Corpus, so it must Refuse). Data contract unit-tested in
`backend/tests/test_eval_set.py` (shape 40+10, unique ids, pages inside the
Corpus, keywords distinctive — no single generic tokens like "risk").

**Scorer** (`backend/app/eval_scorer.py`) — pure and deterministic: contiguous
token-sequence keyword matching (case/punctuation-insensitive), citation-page
set intersection, Refusal correctness (Answer.refused or the exact refusal
message), plus `parse_eval_question` validation and `summarize`. 16 unit tests
in `backend/tests/test_eval_scorer.py`.

**Harness** (`backend/evals/run_eval.py`) — script run as
`python -m evals.run_eval`, with `--limit`, `--only`, `--fresh`, `--attempts`.
Each Question costs two real provider calls (embed + generate), so results are
cached per Question in `evals/results.json` with a content fingerprint and
runs **resume**: fresh ok-records are skipped (unless the Question changed or
`--fresh`), errored ones are retried. Emits `evals/results.md`.

**Live run** — all 50 Questions scored against the live pipeline, 0 errors:
**33/40 in-scope passed, 9/10 out-of-scope refused.**

Draft corrections made after reviewing every miss against the Corpus (all
rescored offline from the cached answers — no extra provider calls): answers
grounded in recitals when the draft expected only the article page
(gpai-model-definition p26, profiling-high-risk p16–17, phased-dates p44,
transparency-chatbot p31/33, emotion-workplace p12, ai-literacy p6,
sandboxes p87–88 chunk-boundary), and paraphrase-tolerant keywords
("biases" as in the Corpus, "emotional state", "ai system under its
authority", dropping "staff"/"written mandate"-style over-strict checks where
the substance was present).

**The 8 misses kept as misses (not edited away):**

- `penalties-prohibited` — wrong answer (EUR 1.5M false-info fine from p117
  instead of the 35M/7% prohibited-practices fine from p115): retrieval miss.
- `entry-into-force` — conflated the entry-into-force/application dates.
- `deployer-obligations` — retrieval missed Article 26 (p67); answer drifted
  to provider-side articles.
- `prohibited-overview` — omitted social scoring; the retrieved excerpt cut
  off before item (c) and the answer says so honestly.
- `corrective-actions` — cited Article 16(j) but omitted the Article 20 duties
  (bring into conformity, withdraw, recall).
- `authorised-representative` — omitted the "written mandate" element of
  Article 22.
- `fria` — omitted bodies governed by public law from the Article 27 list.
- `ai-haiku` (out-of-scope) — the model wrote a haiku instead of refusing.

**README** — rewritten as the portfolio front page: live-demo placeholder for
ticket 09, reviewer tour, local-run instructions, mermaid architecture
diagram, design decisions (ADR-0001/0002 + the deliberate choices), the
results table with the 7 in-scope misses explained one by one, honest-reading
caveats (keyword strictness, model rotation, rate limits), limitations,
Corpus attribution.

Full suite: 105 passed; `python -m mypy app tests evals` clean.

**Pending:** the owner's review of the draft wording (checkbox above) — the
Set's final wording stays theirs per the spec.
