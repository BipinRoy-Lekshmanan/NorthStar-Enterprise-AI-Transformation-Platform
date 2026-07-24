"""Platform Engineering Advisor -- a thin specialization over RagService.

See `app/agents/base_agent.py` for the shared framework; no retrieval,
context, generation, or citation logic lives here.
"""

from __future__ import annotations

from app.agents.base_agent import Advisor

ADVISOR = Advisor(
    advisor_id="platform-engineering",
    display_name="Platform Engineering Advisor",
    description=(
        "Advises on Northstar's platform engineering standards: infrastructure, developer "
        "enablement, and platform reliability."
    ),
    persona=(
        "You are the Northstar Platform Engineering Advisor, a specialist assistant for platform "
        "and infrastructure questions. You answer using only the Northstar platform engineering "
        "reference material supplied below as numbered sources ([S1], [S2], ...)."
    ),
    structure_guidance="Answer\nRecommended Actions\nPlatform Risks or Considerations",
    extra_guidance=(
        "Note when a recommendation depends on self-service platform capabilities versus "
        "requiring direct platform-team involvement."
    ),
    default_filters={"document_id": "NLC-ENG-008"},  # 17_Platform_Engineering.md
)
