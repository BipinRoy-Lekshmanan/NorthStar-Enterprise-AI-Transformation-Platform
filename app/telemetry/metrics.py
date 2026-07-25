"""Prometheus metrics (Milestone 8).

Every collector lives here, once -- `app/api/services/*.py` (the layer
this milestone owns) increments them around calls into the unchanged
Milestone 1-6 modules; nothing is hooked into `RagService`,
`WorkflowEngine`, or any other M1-6 internal. Workflow stage-duration
metrics are computed post-hoc from `WorkflowStageResult.started_at`/
`completed_at` (already persisted) rather than adding hooks into
`WorkflowEngine._advance()`.

No high-cardinality labels: never a raw question, document id, user id,
or citation text as a label value -- only bounded, enumerable values
(advisor ids, workflow ids, status strings, provider/model names).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest

REGISTRY = CollectorRegistry()

# -- API -----------------------------------------------------------------------------

api_requests_total = Counter(
    "api_requests_total", "Total API requests.", ["method", "path", "status"], registry=REGISTRY,
)
api_request_duration_seconds = Histogram(
    "api_request_duration_seconds", "API request latency in seconds.", ["method", "path"], registry=REGISTRY,
)
api_errors_total = Counter(
    "api_errors_total", "Total API error responses.", ["method", "path", "error_code"], registry=REGISTRY,
)
api_active_requests = Gauge("api_active_requests", "Requests currently being processed.", registry=REGISTRY)
rate_limit_rejections_total = Counter(
    "rate_limit_rejections_total", "Requests rejected by the per-category rate limiter.", ["category"],
    registry=REGISTRY,
)

# -- RAG / grounded queries -----------------------------------------------------------------------------

rag_questions_total = Counter(
    "rag_questions_total", "Grounded questions submitted.", ["advisor", "mode", "sufficient_context"],
    registry=REGISTRY,
)
rag_retrieval_duration_seconds = Histogram(
    "rag_retrieval_duration_seconds", "Retrieval-stage duration in seconds.", registry=REGISTRY,
)
rag_model_duration_seconds = Histogram(
    "rag_model_duration_seconds", "Model-generation-stage duration in seconds.", ["provider"], registry=REGISTRY,
)
rag_total_duration_seconds = Histogram(
    "rag_total_duration_seconds", "End-to-end grounded-answer duration in seconds.", registry=REGISTRY,
)
rag_citations_count = Histogram(
    "rag_citations_count", "Citations returned per answer.",
    buckets=(0, 1, 2, 3, 5, 8, 13, float("inf")), registry=REGISTRY,
)
rag_invalid_citations_total = Counter(
    "rag_invalid_citations_total", "Citation ids the model referenced that didn't match a supplied source.",
    registry=REGISTRY,
)
provider_failures_total = Counter(
    "provider_failures_total", "Model/embedding provider call failures.", ["provider", "error_type"],
    registry=REGISTRY,
)
provider_retries_total = Counter(
    "provider_retries_total", "Bounded retry attempts against a provider call.", ["provider", "error_type"],
    registry=REGISTRY,
)
circuit_breaker_state = Gauge(
    "circuit_breaker_state", "Circuit breaker state (0=closed, 1=open, 2=half_open).", ["provider"],
    registry=REGISTRY,
)

# -- Advisors / routing -----------------------------------------------------------------------------

advisor_executions_total = Counter(
    "advisor_executions_total", "Advisor invocations.", ["advisor_id"], registry=REGISTRY,
)
advisor_duration_seconds = Histogram(
    "advisor_duration_seconds", "Per-advisor answer duration in seconds.", ["advisor_id"], registry=REGISTRY,
)
routing_decisions_total = Counter(
    "routing_decisions_total", "Automatic routing decisions.", ["primary_advisor", "fallback_used"],
    registry=REGISTRY,
)
routing_confidence = Histogram(
    "routing_confidence", "Router combined-confidence score.",
    buckets=(0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1.0), registry=REGISTRY,
)
synthesis_failures_total = Counter(
    "synthesis_failures_total", "Multi-advisor/workflow synthesis calls that failed.", ["context"], registry=REGISTRY,
)

# -- Workflows -----------------------------------------------------------------------------

workflows_started_total = Counter(
    "workflows_started_total", "Workflow executions started.", ["workflow_id"], registry=REGISTRY,
)
workflows_completed_total = Counter(
    "workflows_completed_total", "Workflow executions completed.", ["workflow_id"], registry=REGISTRY,
)
workflows_failed_total = Counter(
    "workflows_failed_total", "Workflow executions that reached status=failed.", ["workflow_id"], registry=REGISTRY,
)
workflows_cancelled_total = Counter(
    "workflows_cancelled_total", "Workflow executions cancelled or rejected.", ["workflow_id"], registry=REGISTRY,
)
workflows_awaiting_approval = Gauge(
    "workflows_awaiting_approval", "Executions currently awaiting human approval (set at scrape time).",
    registry=REGISTRY,
)
workflow_stage_duration_seconds = Histogram(
    "workflow_stage_duration_seconds", "Per-stage duration in seconds.", ["workflow_id", "stage_id"],
    registry=REGISTRY,
)
workflow_approval_wait_seconds = Histogram(
    "workflow_approval_wait_seconds", "Time between a stage pausing for approval and a decision being recorded.",
    registry=REGISTRY,
)
workflow_findings_total = Counter(
    "workflow_findings_total", "Findings surfaced across workflow executions.", ["severity"], registry=REGISTRY,
)
workflow_evidence_gaps_total = Counter(
    "workflow_evidence_gaps_total", "Evidence gaps surfaced across workflow executions.", registry=REGISTRY,
)
workflow_conflicts_total = Counter(
    "workflow_conflicts_total", "Conflicts detected across workflow executions.", registry=REGISTRY,
)

# -- Knowledge -----------------------------------------------------------------------------

knowledge_documents_discovered = Gauge(
    "knowledge_documents_discovered", "Documents discovered by the last ingestion run.", registry=REGISTRY,
)
knowledge_chunks_indexed = Gauge(
    "knowledge_chunks_indexed", "Chunks currently indexed in the vector store.", registry=REGISTRY,
)
knowledge_ingestion_failures_total = Counter(
    "knowledge_ingestion_failures_total", "Documents that failed to load during ingestion.", registry=REGISTRY,
)
knowledge_indexing_duration_seconds = Histogram(
    "knowledge_indexing_duration_seconds", "Indexing operation duration in seconds.", ["operation"],
    registry=REGISTRY,
)

# -- Evaluation -----------------------------------------------------------------------------

evaluation_runs_total = Counter(
    "evaluation_runs_total", "Evaluation runs triggered.", ["category"], registry=REGISTRY,
)
evaluation_pass_rate = Gauge(
    "evaluation_pass_rate", "Pass rate of the most recent evaluation run.", ["category"], registry=REGISTRY,
)
evaluation_duration_seconds = Histogram(
    "evaluation_duration_seconds", "Evaluation run duration in seconds.", ["category"], registry=REGISTRY,
)


@contextmanager
def observe_duration(histogram: Histogram, /, **label_values: str) -> Iterator[None]:
    """`with observe_duration(rag_model_duration_seconds, provider="openai"): ...`
    -- times the block and records it, labeled if the histogram has labels."""
    target = histogram.labels(**label_values) if label_values else histogram
    with target.time():
        yield


def render_latest() -> tuple[bytes, str]:
    """Returns `(body, content_type)` for the `/metrics` route."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
