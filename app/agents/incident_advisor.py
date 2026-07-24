"""Incident Management Advisor -- a thin specialization over RagService.

See `app/agents/base_agent.py` for the shared framework; no retrieval,
context, generation, or citation logic lives here.
"""

from __future__ import annotations

from app.agents.base_agent import Advisor

ADVISOR = Advisor(
    advisor_id="incident-management",
    display_name="Incident Management Advisor",
    description=(
        "Advises on Northstar's incident management standard: severity classification, "
        "response procedures, and post-incident review."
    ),
    persona=(
        "You are the Northstar Incident Management Advisor, a specialist assistant for incident "
        "response and reliability questions. You answer using only the Northstar incident "
        "management reference material supplied below as numbered sources ([S1], [S2], ...)."
    ),
    structure_guidance="Answer\nImmediate Actions\nFollow-up Actions\nRisks or Considerations",
    extra_guidance=(
        "Distinguish immediate mitigation/response actions from post-incident follow-up (root "
        "cause analysis, corrective/preventive actions), and reference severity levels when the "
        "question implies a specific severity."
    ),
    default_filters={"document_id": "NLC-ENG-007"},  # 16_Incident_Management.md
    domain_keywords=(
        "incident", "sev1", "sev-1", "severity", "outage", "post-incident",
        "root cause", "war room", "incident commander", "major incident",
    ),
)
