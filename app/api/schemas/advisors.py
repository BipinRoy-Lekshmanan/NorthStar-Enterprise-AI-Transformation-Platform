"""Request/response schemas for advisor endpoints (Milestone 7).

Never exposes an advisor's full internal system prompt -- only a
`prompt_version` string, per the milestone's explicit requirement.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.base_agent import Advisor


class AdvisorOut(BaseModel):
    advisor_id: str
    display_name: str
    description: str
    domains: list[str]
    expected_output_sections: list[str]
    default_document_id: str | None
    prompt_version: str
    enabled: bool = True


def build_advisor_out(advisor: Advisor) -> AdvisorOut:
    return AdvisorOut(
        advisor_id=advisor.advisor_id,
        display_name=advisor.display_name,
        description=advisor.description,
        domains=list(advisor.domain_keywords),
        expected_output_sections=[line.strip() for line in advisor.structure_guidance.splitlines() if line.strip()],
        default_document_id=advisor.default_filters.get("document_id"),
        prompt_version=advisor.prompt_version,
        enabled=True,
    )


class AdvisorQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    document_id: str | None = None
    source_file: str | None = None
    include_diagnostics: bool = False
    include_retrieved_context: bool = False


class RouteOnlyRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class RouteOnlyResponse(BaseModel):
    primary_advisor: str
    supporting_advisors: list[str]
    confidence: float
    rationale: str
    detected_domains: list[str]
    fallback_used: bool
