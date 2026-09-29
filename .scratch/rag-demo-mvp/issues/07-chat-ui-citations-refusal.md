# 07: Chat UI — streaming, Citations, Refusal, examples

**What to build:** The visitor-facing app, wired to the real backend: type or click a Question, watch the answer stream, expand Citation cards to see the verbatim Chunk evidence, and see an honest Refusal when the Corpus can't answer. Session-only history, loading and "server waking up" states, error + retry, dark mode, corpus attribution on the landing page, mobile-usable layout. Everything a recruiter sees in the first minute works.

**Blocked by:** 06 (POST /ask streaming endpoint + abuse limits).

**Status:** ready-for-agent

- [ ] Chat interface sends Questions to the backend and streams answers token by token
- [ ] Expandable Citation cards show Document, page, and verbatim Chunk text per answer
- [ ] Refusal renders as its own honest "couldn't find that in the documents" message
- [ ] 3–5 clickable example Questions ask instantly
- [ ] Session-only message history in the browser; no persistence beyond the tab
- [ ] Loading states: retrieval in progress and "server waking up" for backend cold starts
- [ ] Error state with retry button when the backend reports a failure
- [ ] Dark mode toggle (in MVP per spec decision)
- [ ] Landing page states the Corpus and its attribution (official EU publication, CC BY 4.0) and the fixed-corpus limit
- [ ] Layout usable on mobile; wired to the real backend and demoable in a browser
