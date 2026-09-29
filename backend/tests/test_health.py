"""Tests for the public API seam of the FastAPI app (no real network)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_health_reports_ok(client: TestClient) -> None:
    """A hosting-platform check gets an explicit healthy verdict."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_allows_cross_origin_browser_calls(client: TestClient) -> None:
    """The React app lives on a different origin and must be able to call the API."""
    response = client.options(
        "/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
