"""Tests for `app.config.logging` (Milestone 8) -- the JSON formatter,
the request-id contextvar, and log-format resolution. `configure_logging()`
itself mutates the process-global root logger exactly once (guarded by
a module-level flag) and is exercised live rather than here -- these
tests target the well-isolated pieces around it.
"""

from __future__ import annotations

import json
import logging

from app.config.logging import (
    JsonFormatter,
    RequestIdFilter,
    _resolve_log_format,
    get_request_id,
    reset_request_id,
    set_request_id,
)


def _make_record(msg="hello", **extra):
    record = logging.LogRecord(
        name="app.test", level=logging.INFO, pathname="test.py", lineno=1,
        msg=msg, args=(), exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_request_id_defaults_to_none():
    assert get_request_id() is None


def test_set_get_reset_request_id_round_trips():
    token = set_request_id("abc123")
    try:
        assert get_request_id() == "abc123"
    finally:
        reset_request_id(token)
    assert get_request_id() is None


def test_request_id_filter_injects_contextvar_value():
    token = set_request_id("req-1")
    try:
        record = _make_record()
        RequestIdFilter().filter(record)
        assert record.request_id == "req-1"
    finally:
        reset_request_id(token)


def test_request_id_filter_does_not_override_explicit_extra():
    record = _make_record(request_id="explicit-id")
    RequestIdFilter().filter(record)
    assert record.request_id == "explicit-id"


def test_json_formatter_produces_valid_json_with_core_fields():
    formatter = JsonFormatter(environment="local", application_version="0.8.0")
    record = _make_record("something happened")
    output = json.loads(formatter.format(record))

    assert output["message"] == "something happened"
    assert output["level"] == "INFO"
    assert output["environment"] == "local"
    assert output["service"] == "northstar-platform"
    assert output["application_version"] == "0.8.0"
    assert output["logger"] == "app.test"
    assert "timestamp" in output


def test_json_formatter_includes_extra_fields():
    formatter = JsonFormatter(environment="local", application_version="0.8.0")
    record = _make_record("workflow stage completed", execution_id="exec-1", stage_id="stage-2", duration_ms=42.5)
    output = json.loads(formatter.format(record))

    assert output["execution_id"] == "exec-1"
    assert output["stage_id"] == "stage-2"
    assert output["duration_ms"] == 42.5


def test_json_formatter_redacts_sensitive_extra_fields():
    formatter = JsonFormatter(environment="local", application_version="0.8.0")
    record = _make_record("auth failed", api_key="sk-real-secret")
    output = json.loads(formatter.format(record))
    assert output["api_key"] == "***REDACTED***"
    assert "sk-real-secret" not in formatter.format(record)


def test_json_formatter_includes_current_request_id():
    formatter = JsonFormatter(environment="local", application_version="0.8.0")
    token = set_request_id("req-abc")
    try:
        record = _make_record()
        RequestIdFilter().filter(record)
        output = json.loads(formatter.format(record))
        assert output["request_id"] == "req-abc"
    finally:
        reset_request_id(token)


def test_resolve_log_format_explicit_param_wins():
    assert _resolve_log_format("json") == "json"
    assert _resolve_log_format("TEXT") == "text"


def test_resolve_log_format_env_var_used_when_no_explicit_param(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "json")
    assert _resolve_log_format(None) == "json"


def test_resolve_log_format_defaults_to_text_locally(monkeypatch):
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
    assert _resolve_log_format(None) == "text"


def test_resolve_log_format_defaults_to_json_in_production(monkeypatch):
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    assert _resolve_log_format(None) == "json"
