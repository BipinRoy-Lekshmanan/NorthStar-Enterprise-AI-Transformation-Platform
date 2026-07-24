"""Tests for the API safety-limit middleware (Milestone 7): CORS
restricted to the configured origins, the request-size limit, and the
in-memory rate limiter. Uses the basic `/health` endpoint (no
dependency overrides needed) since these are cross-cutting middleware
concerns, not endpoint-specific behavior.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.middleware.rate_limit import RateLimitMiddleware
from app.api.middleware.request_size_limit import RequestSizeLimitMiddleware


@pytest.fixture
def users_file(tmp_path, monkeypatch):
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps([{"api_key": "viewer-key", "username": "v", "role": "viewer"}]), encoding="utf-8",
    )
    monkeypatch.setenv("AUTH_USERS_FILE", str(path))
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit_log"))
    return path


def test_cors_headers_present_for_allowed_origin(users_file):
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health", headers={"Origin": "http://localhost:8501"})
        assert response.headers.get("access-control-allow-origin") == "http://localhost:8501"


def test_cors_preflight_rejects_a_disallowed_origin(users_file):
    with TestClient(create_app()) as client:
        response = client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" not in response.headers


def test_request_size_limit_rejects_an_oversized_body():
    app = create_app()
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=10)

    with TestClient(app) as client:
        response = client.post("/api/v1/auth/me", content=b"x" * 100, headers={"Content-Length": "100"})
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_rate_limit_rejects_after_the_configured_number_of_requests():
    app = create_app()
    app.add_middleware(RateLimitMiddleware, requests_per_minute=3)

    with TestClient(app) as client:
        for _ in range(3):
            response = client.get("/api/v1/health")
            assert response.status_code == 200

        limited = client.get("/api/v1/health")
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "RATE_LIMITED"


def test_rate_limit_tracks_separate_clients_independently():
    app = create_app()
    app.add_middleware(RateLimitMiddleware, requests_per_minute=1)

    with TestClient(app) as client:
        first = client.get("/api/v1/health", headers={"X-API-Key": "key-a"})
        second = client.get("/api/v1/health", headers={"X-API-Key": "key-b"})
        assert first.status_code == 200
        assert second.status_code == 200
