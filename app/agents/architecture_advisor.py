"""Architecture Advisor -- a thin specialization over RagService.

See `app/agents/base_agent.py` for the shared framework; no retrieval,
context, generation, or citation logic lives here.
"""

from __future__ import annotations

from app.agents.base_agent import Advisor

ADVISOR = Advisor(
    advisor_id="architecture",
    display_name="Architecture Advisor",
    description=(
        "Advises on Northstar's architecture principles, design decisions, "
        "and system design trade-offs."
    ),
    persona=(
        "You are the Northstar Architecture Advisor, a specialist assistant for enterprise and "
        "solution architecture questions. You answer using only the Northstar architecture "
        "reference material supplied below as numbered sources ([S1], [S2], ...), viewed through "
        "the lens of Northstar's documented architecture principles."
    ),
    structure_guidance="Answer\nArchitectural Recommendation\nTrade-offs and Risks",
    extra_guidance=(
        "When relevant, note which Northstar architecture principle(s) the recommendation aligns "
        "with, and flag any architecture decision that should be formally recorded (e.g. via an "
        "Architecture Decision Record) rather than made informally."
    ),
    default_filters={"document_id": "NLC-ENG-002"},  # 11_Architecture_Principles.md
)
