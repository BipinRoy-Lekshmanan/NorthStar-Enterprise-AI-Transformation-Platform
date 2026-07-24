"""Developer Experience Advisor -- a thin specialization over RagService.

See `app/agents/base_agent.py` for the shared framework; no retrieval,
context, generation, or citation logic lives here.
"""

from __future__ import annotations

from app.agents.base_agent import Advisor

ADVISOR = Advisor(
    advisor_id="developer-experience",
    display_name="Developer Experience Advisor",
    description=(
        "Advises on Northstar's developer experience standard: developer productivity, "
        "tooling, and onboarding."
    ),
    persona=(
        "You are the Northstar Developer Experience Advisor, a specialist assistant for "
        "developer productivity and tooling questions. You answer using only the Northstar "
        "developer experience reference material supplied below as numbered sources "
        "([S1], [S2], ...)."
    ),
    structure_guidance="Answer\nRecommended Actions\nRisks or Considerations",
    extra_guidance=(
        "Distinguish self-service developer tooling from changes that require platform-team "
        "involvement, and note any productivity metric the context ties to the recommendation."
    ),
    default_filters={"document_id": "NLC-ENG-009"},  # 18_Developer_Experience.md
    domain_keywords=(
        "developer experience", "onboarding", "developer productivity", "tooling",
        "dx", "developer platform", "inner loop",
    ),
)
