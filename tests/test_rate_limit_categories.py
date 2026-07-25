"""Tests for per-category rate limiting (Milestone 8) --
`app.api.middleware.rate_limit.categorize()` and the middleware's
per-category limits, Retry-After header, and audit event on rejection.
`tests/test_api_safety.py` already covers the original single-limit
behavior; this file is specifically about the category dimension added
in Milestone 8.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.middleware.rate_limit import RateLimitMiddleware, categorize
from app.api.version import API_PREFIX
from app.audit.store import AuditStore


@pytest.mark.parametrize(
    "path,expected_category",
    [
        (f"{API_PREFIX}/query", "query"),
        (f"{API_PREFIX}/advisors", "advisor"),
        (f"{API_PREFIX}/advisors/testing/query", "advisor"),
        (f"{API_PREFIX}/workflows", "workflow"),
        (f"{API_PREFIX}/workflows/executions/abc123", "workflow"),
        (f"{API_PREFIX}/approvals", "workflow"),
        (f"{API_PREFIX}/evaluation/runs", "evaluation"),
        (f"{API_PREFIX}/knowledge/ingest", "administration"),
        (f"{API_PREFIX}/knowledge/index", "administration"),
        (f"{API_PREFIX}/knowledge/rebuild", "administration"),
        (f"{API_PREFIX}/platform/audit", "administration"),
        (f"{API_PREFIX}/knowledge/documents", "default"),  # a GET knowledge route, not an admin action
        (f"{API_PREFIX}/health", "default"),
        (f"{API_PREFIX}/platform/health", "default"),
        ("/metrics", "default"),
    ],
)
def test_categorize_maps_paths_correctly(path, expected_category):
    assert categorize(path) == expected_category


@pytest.fixture
def users_file(tmp_path, monkeypatch):
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps([{"api_key": "viewer-key", "username": "v", "role": "viewer"}]), encoding="utf-8",
    )
    monkeypatch.setenv("AUTH_USERS_FILE", str(path))
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit_log"))
    return path


def test_category_limits_are_independent(users_file, tmp_path):
    """Exceeding one category's limit must not affect another category's
    budget for the same actor."""
    app = create_app()
    app.add_middleware(
        RateLimitMiddleware, requests_per_minute=100, category_limits={"default": 2},
    )

    with TestClient(app) as client:
        for _ in range(2):
            response = client.get("/api/v1/health", headers={"X-API-Key": "viewer-key"})
            assert response.status_code == 200

        limited = client.get("/api/v1/health", headers={"X-API-Key": "viewer-key"})
        assert limited.status_code == 429

        # A different category (advisor, not default) for the same actor
        # has its own, unexhausted budget.
        unaffected = client.get("/api/v1/advisors", headers={"X-API-Key": "viewer-key"})
        assert unaffected.status_code == 200


def test_429_response_includes_retry_after_header(users_file, tmp_path):
    app = create_app()
    app.add_middleware(RateLimitMiddleware, requests_per_minute=1, category_limits={})

    with TestClient(app) as client:
        client.get("/api/v1/health", headers={"X-API-Key": "viewer-key"})
        limited = client.get("/api/v1/health", headers={"X-API-Key": "viewer-key"})
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) >= 1
        body = limited.json()
        assert body["error"]["details"]["category"] == "default"
        assert body["error"]["details"]["limit"] == 1


def test_429_records_an_audit_event(users_file, tmp_path):
    app = create_app()
    app.add_middleware(RateLimitMiddleware, requests_per_minute=1, category_limits={})

    with TestClient(app) as client:
        client.get("/api/v1/health", headers={"X-API-Key": "viewer-key"})
        client.get("/api/v1/health", headers={"X-API-Key": "viewer-key"})

    store = AuditStore.from_env()
    events = [e for e in store.list_events() if e.action == "rate_limit_exceeded"]
    assert len(events) == 1
    assert events[0].actor == "viewer-key"
    assert events[0].resource_id == "default"
    assert events[0].outcome == "rejected"
