"""Tests for `app.api.middleware.security_headers.SecurityHeadersMiddleware`
(Milestone 8). Uses the health endpoint (no auth needed, no fixtures
required beyond a plain `create_app()`) to check every JSON API
response gets the strict header set, and `/docs` gets the relaxed CSP
its Swagger UI bundle needs.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app

_EXPECTED_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "geolocation=(), camera=(), microphone=()",
    "strict-transport-security": "max-age=31536000; includeSubDomains",
    "x-permitted-cross-domain-policies": "none",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    users_file = tmp_path / "users.json"
    users_file.write_text(
        json.dumps([{"api_key": "viewer-key", "username": "v", "role": "viewer"}]), encoding="utf-8",
    )
    monkeypatch.setenv("AUTH_USERS_FILE", str(users_file))
    with TestClient(create_app()) as test_client:
        yield test_client


def test_every_response_gets_the_full_security_header_set(client):
    response = client.get("/api/v1/health")
    for name, value in _EXPECTED_HEADERS.items():
        assert response.headers.get(name) == value


def test_json_api_responses_get_a_strict_csp(client):
    response = client.get("/api/v1/health")
    assert response.headers.get("content-security-policy") == "default-src 'none'; frame-ancestors 'none'"


def test_error_responses_also_get_security_headers(client):
    response = client.get("/api/v1/workflows/does-not-exist", headers={"X-API-Key": "viewer-key"})
    assert response.status_code == 404
    for name, value in _EXPECTED_HEADERS.items():
        assert response.headers.get(name) == value


def test_unauthenticated_401_responses_also_get_security_headers(client):
    response = client.get("/api/v1/workflows")
    assert response.status_code == 401
    for name, value in _EXPECTED_HEADERS.items():
        assert response.headers.get(name) == value


def test_docs_page_gets_a_relaxed_csp_allowing_its_cdn_bundle(client):
    response = client.get("/docs")
    assert response.status_code == 200
    csp = response.headers.get("content-security-policy")
    assert "cdn.jsdelivr.net" in csp
    assert csp != "default-src 'none'; frame-ancestors 'none'"


def test_redoc_page_gets_a_relaxed_csp(client):
    response = client.get("/redoc")
    assert response.status_code == 200
    assert "cdn.jsdelivr.net" in response.headers.get("content-security-policy")
