"""Testing Advisor -- a thin specialization over RagService.

See `app/agents/base_agent.py` for the shared framework; no retrieval,
context, generation, or citation logic lives here.
"""

from __future__ import annotations

from app.agents.base_agent import Advisor

ADVISOR = Advisor(
    advisor_id="testing",
    display_name="Testing Advisor",
    description=(
        "Advises on Northstar's testing strategy: test coverage expectations, quality "
        "gates, and release-readiness evidence."
    ),
    persona=(
        "You are the Northstar Testing Advisor, a specialist assistant for software quality and "
        "testing questions. You answer using only the Northstar testing reference material "
        "supplied below as numbered sources ([S1], [S2], ...)."
    ),
    structure_guidance="Answer\nRecommended Test Coverage\nRisks or Gaps",
    extra_guidance=(
        "Where relevant, distinguish test types (unit, integration, security, performance, "
        "regression) and note whether documented evidence of testing is required before release."
    ),
    default_filters={"document_id": "NLC-ENG-005"},  # 14_Testing_Strategy.md
    domain_keywords=(
        "testing", "test coverage", "quality gate", "unit test", "integration test",
        "regression test", "qa", "test evidence", "test strategy",
    ),
)
