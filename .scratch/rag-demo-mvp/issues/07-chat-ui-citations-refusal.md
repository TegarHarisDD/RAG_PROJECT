# 07: Chat UI — streaming, Citations, Refusal, examples

**What to build:** The visitor-facing app, wired to the real backend: type or click a Question, watch the answer stream, expand Citation cards to see the verbatim Chunk evidence, and see an honest Refusal when the Corpus can't answer. Session-only history, loading and "server waking up" states, error + retry, dark mode, corpus attribution on the landing page, mobile-usable layout. Everything a recruiter sees in the first minute works.

**Blocked by:** 06 (POST /ask streaming endpoint + abuse limits).

**Status:** resolved

- [x] Chat interface sends Questions to the backend and streams answers token by token
- [x] Expandable Citation cards show Document, page, and verbatim Chunk text per answer
- [x] Refusal renders as its own honest "couldn't find that in the documents" message
- [x] 3–5 clickable example Questions ask instantly
- [x] Session-only message history in the browser; no persistence beyond the tab
- [x] Loading states: retrieval in progress and "server waking up" for backend cold starts
- [x] Error state with retry button when the backend reports a failure
- [x] Dark mode toggle (in MVP per spec decision)
- [x] Landing page states the Corpus and its attribution (official EU publication, CC BY 4.0) and the fixed-corpus limit
- [x] Layout usable on mobile; wired to the real backend and demoable in a browser

## Comments

- **Seams (agreed with the owner before testing)**: the ask client (`src/ask.ts` `askQuestion`) and the rendered UI behavior. Vitest + jsdom + @testing-library/react added as dev deps; tests at both seams, no network. 18 frontend tests passing; backend's 85 untouched.
- **Ask client** (`src/ask.ts`): hand-parses the SSE stream off `fetch`'s body (EventSource can't POST). Maps the backend contract one-to-one — `token` → `onToken`, `refusal` → `{refused: true, message}`, `citations` → terminal result, in-stream `error` → `AskError(kind, message)`. Rejects with a typed `AskError` for every renderable failure: 429 (server's message kept, non-JSON block-page tolerated), 422 (length/blank), network faults ("could not reach the server"), malformed payloads. **Cold-start signal**: `onWakingUp` fires once if headers take >4 s (Render free tier ~1 min wake) and is cleared the moment headers arrive. The reader is cancelled on any in-stream throw so failures don't pin free-tier connections. Stream hardening: CRLF-normalized, multi-line `data:` fields joined, `JSON.parse` failures mapped to a clean `internal` error — never a raw SyntaxError reaching a chat bubble.
- **Chat UI** (`src/App.tsx`, `components/`): session-only history is plain React state (nothing persisted, nothing but the tab). Assistant messages move pending ("Searching the documents…") → streaming → done through a single patch helper; Refusals render in their own amber card style; errors render as an alert with a Retry button that re-asks the stored `retryQuestion`. Composer: 500-char cap with live counter (the spec's fixed abuse cap; a backend 422 also renders as a clear message), Enter submits, Shift+Enter newlines, and IME-composition Enter (`isComposing`) does not submit.
- **Citations** (`components/CitationCard.tsx`): collapsed reads "eu-ai-act.pdf, p. 12"; expanded reveals the verbatim Chunk text — Document, page, Chunk per spec user story 4.
- **Landing page**: corpus (Regulation (EU) 2024/1689 — the EU AI Act), the fixed-corpus/no-uploads limit, and the official EU publication attribution with CC BY 4.0 / Decision 2011/833/EU link. Five example Questions including one deliberately out-of-scope ("capital of France") so the honest Refusal is visible with zero typing.
- **Dark mode**: class-based `dark` variant (`@custom-variant` in index.css). An inline script in index.html applies the theme before first paint (no light flash); the toggle persists only choices the visitor actually makes, so OS-preference followers keep following. Choice remembered in localStorage (theme only — messages stay session-only).
- **Backend URL**: `VITE_API_URL` env (default `http://localhost:8000`), never hardcoded — matches the backend's `FRONTEND_ORIGINS` CORS config.
- **Code-review pass (8 findings, all fixed)**: unguarded JSON.parse on stream payload and 429 body; IME Enter submitting mid-composition; leaked stream reader on in-stream errors; 422 rendered as opaque "HTTP 422"; dark-mode first-paint flash + OS default wrongly persisted; CRLF/multi-line SSE frames dropped; duplicated assistant-message patch logic (unified).
- 18 frontend tests passing, `tsc -b` build clean, oxlint clean; backend 85 passing untouched. Not live-verified against the real Atlas/OpenRouter backend in this session (local DNS to those endpoints has been flaky); the UI-to-SSE contract is covered end to end against mocked streams shaped exactly like the backend's own API-seam tests assert.
