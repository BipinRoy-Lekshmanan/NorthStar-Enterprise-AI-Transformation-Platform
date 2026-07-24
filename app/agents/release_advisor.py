"""Release Advisor -- a thin specialization over RagService.

See `app/agents/base_agent.py` for the shared framework; no retrieval,
context, generation, or citation logic lives here.
"""

from __future__ import annotations

from app.agents.base_agent import Advisor

ADVISOR = Advisor(
    advisor_id="release",
    display_name="Release Advisor",
    description=(
        "Advises on Northstar's release management standard: release evidence, "
        "canary/rollback procedures, and change approval."
    ),
    persona=(
        "You are the Northstar Release Advisor, a specialist assistant for release and "
        "deployment questions. You answer using only the Northstar release management "
        "reference material supplied below as numbered sources ([S1], [S2], ...)."
    ),
    structure_guidance="Answer\nRequired Evidence\nRisks or Considerations",
    extra_guidance=(
        "Distinguish evidence required before a release from actions taken after a failed "
        "deployment (e.g. rollback), and note which approvals are mandatory versus advisory."
    ),
    default_filters={"document_id": "NLC-ENG-006"},  # 15_Release_Management.md
    domain_keywords=(
        "release", "deployment", "canary", "rollback", "release management",
        "change approval", "release evidence", "release readiness",
    ),
)
