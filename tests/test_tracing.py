"""Tests for `app.telemetry.tracing` (Milestone 8) -- disabled by
default, `configure_tracing()` is idempotent, and `traced_span()` marks
a span as an error without swallowing the underlying exception.

`trace.set_tracer_provider()` is itself a one-shot guard inside
OpenTelemetry (by design -- the first caller in a process wins, so one
library can't silently override another's provider), so these tests
verify `configure_tracing()`'s own `_configured` bookkeeping rather
than reaching into OpenTelemetry's private internals to force a
re-installable provider.
"""

from __future__ import annotations

import pytest

import app.telemetry.tracing as tracing_module
from app.config.settings import TelemetrySettings
from app.telemetry.tracing import configure_tracing, traced_span


def test_traced_span_is_a_safe_no_op_when_tracing_never_configured():
    """Before `configure_tracing(enabled=True)` ever runs, the global
    tracer provider is OpenTelemetry's own no-op provider --
    `traced_span()` must not raise either way."""
    with traced_span("some.operation", advisor_id="testing") as span:
        assert span is not None


def test_traced_span_yields_control_and_returns_normally():
    executed = False
    with traced_span("some.operation"):
        executed = True
    assert executed


def test_traced_span_propagates_exceptions():
    with pytest.raises(ValueError, match="boom"):
        with traced_span("failing.operation"):
            raise ValueError("boom")


def test_traced_span_drops_none_valued_attributes():
    # None-valued attributes must not raise (OpenTelemetry's own
    # set_attribute rejects None) -- traced_span() filters them out.
    with traced_span("some.operation", provider=None, advisor_id="testing"):
        pass


def test_configure_tracing_is_a_no_op_when_disabled(monkeypatch):
    monkeypatch.setattr(tracing_module, "_configured", False)
    configure_tracing(enabled=False, environment="local")
    assert tracing_module._configured is False


def test_configure_tracing_is_idempotent_once_enabled(monkeypatch):
    monkeypatch.setattr(tracing_module, "_configured", True)
    # Already configured -- a second call (even with different args)
    # must not raise and must leave `_configured` as-is.
    configure_tracing(enabled=True, environment="production", otlp_endpoint="http://example.invalid:4318")
    assert tracing_module._configured is True


# -- TelemetrySettings -----------------------------------------------------------------------------


def test_telemetry_settings_defaults_to_disabled():
    settings = TelemetrySettings.from_env(env={})
    assert settings.tracing_enabled is False
    assert settings.otlp_endpoint is None


def test_telemetry_settings_reads_enabled_flag():
    settings = TelemetrySettings.from_env(env={"TRACING_ENABLED": "true"})
    assert settings.tracing_enabled is True


def test_telemetry_settings_reads_otlp_endpoint():
    settings = TelemetrySettings.from_env(env={"OTLP_ENDPOINT": "http://otel-collector:4318"})
    assert settings.otlp_endpoint == "http://otel-collector:4318"


def test_telemetry_settings_blank_otlp_endpoint_is_none():
    settings = TelemetrySettings.from_env(env={"OTLP_ENDPOINT": ""})
    assert settings.otlp_endpoint is None
