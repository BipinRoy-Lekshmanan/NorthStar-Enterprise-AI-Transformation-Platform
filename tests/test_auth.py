"""Tests for `app.auth` -- role hierarchy, the local user directory, and
the new `ApiSettings`/`AuthSettings` configuration classes (Milestone 7).
"""

import json

import pytest

from app.auth.roles import Role, role_at_least
from app.auth.users import UserDirectoryError, load_users
from app.config.settings import ApiSettings, AuthSettings, ConfigurationError


# -- roles -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "actual,minimum,expected",
    [
        (Role.ADMINISTRATOR, Role.VIEWER, True),
        (Role.ADMINISTRATOR, Role.ADMINISTRATOR, True),
        (Role.VIEWER, Role.ADMINISTRATOR, False),
        (Role.REVIEWER, Role.ENGINEER, True),
        (Role.ENGINEER, Role.REVIEWER, False),
        (Role.VIEWER, Role.VIEWER, True),
    ],
)
def test_role_at_least(actual, minimum, expected):
    assert role_at_least(actual, minimum) is expected


# -- users -----------------------------------------------------------------------------


def _write_users(tmp_path, entries):
    path = tmp_path / "users.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def test_load_users_returns_dict_keyed_by_api_key(tmp_path):
    path = _write_users(tmp_path, [
        {"api_key": "k1", "username": "alice", "role": "viewer"},
        {"api_key": "k2", "username": "bob", "role": "administrator"},
    ])
    users = load_users(path)
    assert set(users) == {"k1", "k2"}
    assert users["k1"].username == "alice"
    assert users["k1"].role == Role.VIEWER
    assert users["k2"].role == Role.ADMINISTRATOR


def test_api_key_is_excluded_from_serialization(tmp_path):
    path = _write_users(tmp_path, [{"api_key": "secret-key", "username": "alice", "role": "viewer"}])
    user = load_users(path)["secret-key"]
    dumped = user.model_dump()
    assert "api_key" not in dumped
    assert dumped == {"username": "alice", "role": Role.VIEWER}


def test_missing_users_file_raises_clear_error(tmp_path):
    with pytest.raises(UserDirectoryError, match="not found"):
        load_users(tmp_path / "does_not_exist.json")


def test_malformed_json_raises_clear_error(tmp_path):
    path = tmp_path / "users.json"
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(UserDirectoryError, match="not valid JSON"):
        load_users(path)


def test_invalid_role_raises_clear_error(tmp_path):
    path = _write_users(tmp_path, [{"api_key": "k1", "username": "alice", "role": "superuser"}])
    with pytest.raises(UserDirectoryError, match="Invalid user entry"):
        load_users(path)


def test_duplicate_api_key_raises_clear_error(tmp_path):
    path = _write_users(tmp_path, [
        {"api_key": "k1", "username": "alice", "role": "viewer"},
        {"api_key": "k1", "username": "bob", "role": "administrator"},
    ])
    with pytest.raises(UserDirectoryError, match="Duplicate api_key"):
        load_users(path)


def test_empty_users_file_raises_clear_error(tmp_path):
    path = _write_users(tmp_path, [])
    with pytest.raises(UserDirectoryError, match="contains no users"):
        load_users(path)


def test_real_example_users_file_loads_successfully():
    from app.config.settings import PROJECT_ROOT

    path = PROJECT_ROOT / "data" / "auth" / "users.example.json"
    users = load_users(path)
    assert len(users) == 4
    assert {user.role for user in users.values()} == set(Role)


# -- ApiSettings -----------------------------------------------------------------------------


def test_api_settings_defaults():
    settings = ApiSettings.from_env(env={})
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert "http://localhost:8501" in settings.cors_allowed_origins


def test_api_settings_invalid_port_raises():
    with pytest.raises(ConfigurationError, match="API_PORT"):
        ApiSettings.from_env(env={"API_PORT": "99999"})


def test_api_settings_empty_cors_origins_raises():
    with pytest.raises(ConfigurationError, match="API_CORS_ORIGINS"):
        ApiSettings.from_env(env={"API_CORS_ORIGINS": ""})


def test_api_settings_invalid_question_length_raises():
    with pytest.raises(ConfigurationError, match="API_MAX_QUESTION_LENGTH"):
        ApiSettings.from_env(env={"API_MAX_QUESTION_LENGTH": "0"})


def test_api_settings_rate_limit_default():
    settings = ApiSettings.from_env(env={})
    assert settings.rate_limit_per_minute == 120


def test_api_settings_invalid_rate_limit_raises():
    with pytest.raises(ConfigurationError, match="API_RATE_LIMIT_PER_MINUTE"):
        ApiSettings.from_env(env={"API_RATE_LIMIT_PER_MINUTE": "0"})


# -- AuthSettings -----------------------------------------------------------------------------


def test_auth_settings_defaults():
    settings = AuthSettings.from_env(env={})
    assert str(settings.users_file).replace("\\", "/").endswith("data/auth/users.json")


def test_auth_settings_does_not_require_file_to_exist():
    # Deliberately lenient at settings-validation time -- only the API's
    # startup lifespan requires the file to actually exist.
    settings = AuthSettings.from_env(env={"AUTH_USERS_FILE": "definitely/does/not/exist.json"})
    assert settings.users_file is not None
