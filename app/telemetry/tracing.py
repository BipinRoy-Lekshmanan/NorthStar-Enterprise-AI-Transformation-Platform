"""Optional OpenTelemetry tracing (Milestone 8). Disabled by default.

`traced_span()` is safe to sprinkle at any `app/api/services/` boundary
regardless of whether tracing is enabled -- when disabled,
`opentelemetry`'s own default global tracer provider is a genuine no-op
(`NoOpTracer`), so every call here costs a few attribute-free no-ops,
not a real span. Spans are created at the boundary this milestone owns
(around calls into `RagService`/`WorkflowEngine`/the evaluators), never
by adding hooks into Milestone 1-6 internals. Provider/model names and
token counts may appear as span attributes; no prompt or document
content ever does.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

from app.api.version import APP_VERSION

SERVICE_NAME = "northstar-platform"
TRACER_NAME = "northstar-platform"

_configured = False


def configure_tracing(*, enabled: bool, environment: str, otlp_endpoint: str | None = None) -> None:
    """Called once, at startup (safe to call every time -- a no-op
    unless `enabled` and not already configured). Exports to a local
    OTLP collector if `otlp_endpoint` is set, otherwise to the console
    (no cloud vendor, no collector required to see spans locally)."""
    global _configured
    if _configured or not enabled:
        return

    resource = Resource.create({
        "service.name": SERVICE_NAME,
        "service.version": APP_VERSION,
        "deployment.environment": environment,
    })
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    else:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _configured = True


@contextmanager
def traced_span(name: str, **attributes: Any) -> Iterator[Span]:
    """`with traced_span("rag.ask", advisor="testing", provider="openai"): ...`
    -- `None`-valued attributes are dropped rather than stringified, and
    an exception raised inside the block marks the span as an error
    (with its type/message, never its full traceback) before
    re-raising unchanged."""
    tracer = trace.get_tracer(TRACER_NAME)
    with tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise
