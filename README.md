# rag-portfolio-demo

A public RAG portfolio demo: ask questions about a fixed document set and get
streamed answers with citations.

**Status:** under construction — see `.scratch/rag-demo-mvp/` for the spec and
tickets. This README will grow into the full architecture/evaluation write-up
as milestones land.

## Running locally

**Backend** (Python 3.10+, FastAPI):

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in real values; never committed
uvicorn app.main:app --reload
```

**Frontend** (Node 22+, React + Vite + Tailwind):

```bash
cd frontend
npm install
npm run dev
```

The frontend dev server runs on `http://localhost:5173`; the backend API on
`http://localhost:8000` with `GET /health` for platform checks.
