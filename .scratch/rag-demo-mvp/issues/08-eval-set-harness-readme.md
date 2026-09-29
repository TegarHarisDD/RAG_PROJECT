# 08: Eval Set + harness + README

**What to build:** Measured quality, published: a draft Eval Set of ~50 Eval Questions (≈40 in-scope, 10 out-of-scope) for the owner to review, a deterministic scorer (expected keywords in answers, citation page match, Refusal correctness on out-of-scope), results run against the live pipeline, and the full README — architecture diagram, design decisions, eval results table, limitations. The repo now reads as a portfolio artifact in ten minutes.

**Blocked by:** 07 (chat UI — streaming, Citations, Refusal, examples).

**Status:** ready-for-agent

- [ ] ~50 Eval Questions drafted from the Corpus for owner review (in-scope and out-of-scope mixed)
- [ ] Deterministic scorer: expected-keyword matching in answers, citation page match, correct Refusals on out-of-scope
- [ ] Harness runs the Eval Set against the pipeline and emits a results table
- [ ] Owner reviews and corrects the draft; final wording stays theirs
- [ ] README: architecture diagram, design decisions (linking ADRs), eval results, limitations, how to run
- [ ] Eval results table lands in the README with the accuracy targets reported honestly
- [ ] Harness is a script, not part of the test suite (per spec testing decisions)
