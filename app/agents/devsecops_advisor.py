"""DevSecOps Advisor -- a thin specialization over RagService.

See `app/agents/base_agent.py` for the shared framework; no retrieval,
context, generation, or citation logic lives here.
"""

from __future__ import annotations

from app.agents.base_agent import Advisor

ADVISOR = Advisor(
    advisor_id="devsecops",
    display_name="DevSecOps Advisor",
    description=(
        "Advises on Northstar's DevSecOps standards: CI/CD pipeline security, secure "
        "coding, SAST/DAST, and delivery lifecycle controls."
    ),
    persona=(
        "You are the Northstar DevSecOps Advisor, a specialist assistant for secure software "
        "delivery questions. You answer using only the Northstar DevSecOps reference material "
        "supplied below as numbered sources ([S1], [S2], ...)."
    ),
    structure_guidance="Answer\nRequired Controls\nRisks or Considerations",
    extra_guidance=(
        "Identify which delivery-lifecycle stage (plan/design/develop/build/test/secure/release/"
        "deploy) a control applies to when the context makes that clear, and distinguish enforced "
        "gates from recommended practice."
    ),
    default_filters={"document_id": "NLC-ENG-004"},  # 13_DevSecOps_Standards.md
)
