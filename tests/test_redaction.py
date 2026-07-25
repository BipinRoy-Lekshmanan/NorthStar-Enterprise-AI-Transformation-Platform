"""Tests for `app.config.redaction` (Milestone 8)."""

from app.config.redaction import REDACTED_VALUE, is_sensitive_key, redact


def test_is_sensitive_key_matches_known_markers():
    assert is_sensitive_key("api_key")
    assert is_sensitive_key("openai_api_key")
    assert is_sensitive_key("Authorization")
    assert is_sensitive_key("PASSWORD")
    assert is_sensitive_key("client_secret")
    assert is_sensitive_key("auth_token")
    assert is_sensitive_key("session_id")
    assert is_sensitive_key("cookie_value")


def test_is_sensitive_key_allowlist_prevents_false_positives():
    # Regression test: found live via `python -m app.config show --redacted`,
    # which redacted a plain integer limit because "token" is a substring
    # of "tokens".
    assert not is_sensitive_key("llm_max_output_tokens")
    assert not is_sensitive_key("input_tokens")
    assert not is_sensitive_key("output_tokens")


def test_is_sensitive_key_unrelated_field_not_matched():
    assert not is_sensitive_key("host")
    assert not is_sensitive_key("port")
    assert not is_sensitive_key("chunk_size")


def test_redact_replaces_sensitive_dict_values():
    result = redact({"api_key": "sk-real-secret", "host": "127.0.0.1"})
    assert result == {"api_key": REDACTED_VALUE, "host": "127.0.0.1"}


def test_redact_recurses_into_nested_dicts():
    result = redact({"rag": {"llm_api_key": "secret", "llm_temperature": 0.0}})
    assert result == {"rag": {"llm_api_key": REDACTED_VALUE, "llm_temperature": 0.0}}


def test_redact_recurses_into_lists_and_tuples():
    result = redact({"users": [{"api_key": "k1"}, {"api_key": "k2"}]})
    assert result == {"users": [{"api_key": REDACTED_VALUE}, {"api_key": REDACTED_VALUE}]}

    result = redact({"origins": ("http://localhost:8501",)})
    assert result == {"origins": ("http://localhost:8501",)}


def test_redact_leaves_non_container_values_unchanged():
    assert redact("plain string") == "plain string"
    assert redact(42) == 42
    assert redact(None) is None
