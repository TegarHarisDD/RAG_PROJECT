# 09: Deploy — Vercel + Render + public GitHub repo

**What to build:** The demo goes live as a public portfolio artifact: the public GitHub repo `rag-portfolio-demo`, the backend on Render (free tier) with secrets in its env only, the frontend on Vercel pointing at it with CORS working, and the cold-start "waking up" experience verified against the real sleeping backend. Final state: a recruiter clicks the URL and gets a streamed, cited answer.

**Blocked by:** 08 (eval set + harness + README).

**Status:** ready-for-agent

- [ ] Public GitHub repo created and pushed (name: `rag-portfolio-demo`); no secrets committed
- [ ] Backend deployed on Render free tier; OpenRouter + Atlas credentials in Render env only
- [ ] Frontend deployed on Vercel hobby tier; API base URL configured; CORS between the two works
- [ ] `GET /health` passes platform checks; deploy pipeline from git push works for both
- [ ] Cold-start UX verified against the real sleeping backend (waking message appears, then answer streams)
- [ ] Live end-to-end check: streamed answer with Citations from the deployed frontend
- [ ] Abuse limits confirmed active in production (per-IP hourly, length cap, daily stop)
