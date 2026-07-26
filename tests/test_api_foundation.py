"""Tests for the FastAPI application skeleton (Milestone 7): app
creation, the health endpoint, and OpenAPI generation. Uses FastAPI's
`TestClient` -- no real network, no uvicorn process.
"""

from fastapi.testclient import TestClient

from app.api.main import APP_VERSION, app

client = TestClient(app)


def test_app_has_expected_metadata():
    assert app.title == "HAIE Platform"
    assert app.version == APP_VERSION


def test_health_endpoint_returns_ok():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_schema_generates_without_error():
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "HAIE Platform"
    assert "/api/v1/health" in schema["paths"]


def test_docs_page_is_served():
    response = client.get("/docs")
    assert response.status_code == 200
