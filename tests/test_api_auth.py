"""Tests for authentication/authorization (Milestone 7): `require_role`
composition directly, and the real `/api/v1/auth/me` route through a
freshly-constructed app (never the module-level `app.api.main.app`
singleton, so tests don't interfere with each other's state) pointed at
a tmp_path fixture users file via a monkeypatched `AUTH_USERS_FILE`.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.errors import ApiError
from app.api.main import create_app
from app.auth.dependencies import require_role
from app.auth.roles import Role
from app.auth.users import User, UserDirectoryError

# -- require_role, tested directly (no app/route needed) -----------------------------


def test_require_role_allows_a_role_with_more_authority():
    check = require_role(Role.REVIEWER)
    user = User(username="a", role=Role.ADMINISTRATOR, api_key="k")
    assert check(user) is user


def test_require_role_allows_exact_match():
    check = require_role(Role.ENGINEER)
    user = User(username="a", role=Role.ENGINEER, api_key="k")
    assert check(user) is user


def test_require_role_rejects_insufficient_role():
    check = require_role(Role.REVIEWER)
    user = User(username="a", role=Role.VIEWER, api_key="k")
    with pytest.raises(ApiError) as exc_info:
        check(user)
    assert exc_info.value.status_code == 403
    assert exc_info.value.code.value == "FORBIDDEN"
    assert exc_info.value.details == {"required_role": "reviewer", "actual_role": "viewer"}


# -- /api/v1/auth/me, through a real (isolated) app -----------------------------


@pytest.fixture
def users_file(tmp_path, monkeypatch):
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps([
            {"api_key": "viewer-key", "username": "viewer-user", "role": "viewer"},
            {"api_key": "admin-key", "username": "admin-user", "role": "administrator"},
        ]),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTH_USERS_FILE", str(path))
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit_log"))
    return path


@pytest.fixture
def client(users_file):
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_missing_api_key_returns_401(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_invalid_api_key_returns_401(client):
    response = client.get("/api/v1/auth/me", headers={"X-API-Key": "not-a-real-key"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_valid_api_key_returns_resolved_user(client):
    response = client.get("/api/v1/auth/me", headers={"X-API-Key": "viewer-key"})
    assert response.status_code == 200
    body = response.json()
    assert body == {"username": "viewer-user", "role": "viewer"}
    assert "api_key" not in body


def test_administrator_key_resolves_to_administrator_role(client):
    response = client.get("/api/v1/auth/me", headers={"X-API-Key": "admin-key"})
    assert response.status_code == 200
    assert response.json()["role"] == "administrator"


# -- startup validation -----------------------------------------------------------------


def test_missing_users_file_fails_app_startup(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_USERS_FILE", str(tmp_path / "does_not_exist.json"))
    app = create_app()
    with pytest.raises(UserDirectoryError, match="not found"):
        with TestClient(app):
            pass
