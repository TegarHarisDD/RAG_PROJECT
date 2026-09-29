"""FastAPI application entry point."""
import os

from dotenv import load_dotenv
from fastapi import FastAPI

# Backend configuration lives in .env (see .env.example); secrets never
# leave this process or get committed.
load_dotenv()

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="rag-portfolio-demo")

# The React frontend runs on a different origin (Vercel in prod, Vite dev
# server locally), so browser calls need CORS. Origins are env-configured,
# never hardcoded.
_FRONTEND_ORIGINS: list[str] = [
    origin.strip()
    for origin in os.environ.get("FRONTEND_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_FRONTEND_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health() -> dict[str, str]:
    """Health check for hosting-platform monitoring."""
    return {"status": "ok"}
