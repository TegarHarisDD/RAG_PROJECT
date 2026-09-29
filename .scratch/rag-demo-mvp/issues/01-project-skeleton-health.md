# 01: Project skeleton + health endpoint

**What to build:** Both halves of the app exist and run locally: a React + Vite + Tailwind TypeScript frontend and a FastAPI backend with a health endpoint a hosting platform could ping. Git history starts here, with a README stub. Nothing does RAG work yet — this ticket proves the project boots.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] Frontend scaffolded with Vite (React + TypeScript + Tailwind), starts and renders a placeholder page
- [ ] Backend scaffolded with FastAPI, starts and serves the API
- [ ] `GET /health` returns an OK response suitable for hosting-platform checks
- [ ] README stub exists (title, one-line description, how to run both halves)
- [ ] Git repo initialized (`git init`) with the scaffold as the first commit
- [ ] Environment/config convention established (secrets only in backend env, none committed)
