"""Consolidated capacity-limit view (Milestone 8).

Every individual limit already has exactly one source of truth in its
own settings class (`RagSettings.llm_max_output_tokens`,
`ApiSettings.max_upload_bytes`, ...) -- this module doesn't introduce a
second source of truth for any of them, it just gathers the ones that
actually bound request size/cost/concurrency into one read-only
snapshot for operational visibility (`python -m app.config limits`),
since today they're scattered across five different settings classes
with no single place an operator can see them all together.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.production_checks import SettingsBundle


@dataclass(frozen=True)
class CapacityLimits:
    max_question_length: int
    max_upload_bytes: int
    api_request_timeout_seconds: float
    rate_limit_per_minute: int
    rate_limit_category_overrides: dict[str, int]
    retrieval_top_k: int
    context_max_chunks: int
    context_max_characters: int
    llm_max_output_tokens: int
    llm_timeout_seconds: float
    llm_max_concurrent_requests: int
    embedding_max_concurrent_requests: int
    chunk_size: int
    chunk_overlap: int
    workflow_max_stages: int
    daily_budget_usd: float | None
    budget_warning_ratio: float

    @classmethod
    def from_settings_bundle(cls, bundle: SettingsBundle) -> "CapacityLimits":
        return cls(
            max_question_length=bundle.api.max_question_length,
            max_upload_bytes=bundle.api.max_upload_bytes,
            api_request_timeout_seconds=bundle.api.request_timeout_seconds,
            rate_limit_per_minute=bundle.api.rate_limit_per_minute,
            rate_limit_category_overrides=dict(bundle.api.rate_limit_category_overrides),
            retrieval_top_k=bundle.retrieval.retrieval_top_k,
            context_max_chunks=bundle.rag.context_max_chunks,
            context_max_characters=bundle.rag.context_max_characters,
            llm_max_output_tokens=bundle.rag.llm_max_output_tokens,
            llm_timeout_seconds=bundle.rag.llm_timeout_seconds,
            llm_max_concurrent_requests=bundle.rag.llm_max_concurrent_requests,
            embedding_max_concurrent_requests=bundle.retrieval.embedding_max_concurrent_requests,
            chunk_size=bundle.ingestion.chunk_size,
            chunk_overlap=bundle.ingestion.chunk_overlap,
            workflow_max_stages=bundle.workflow.workflow_max_stages,
            daily_budget_usd=bundle.cost.daily_budget_usd,
            budget_warning_ratio=bundle.cost.budget_warning_ratio,
        )
