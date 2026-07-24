"""AI Engineering Advisor -- a thin specialization over RagService.

See `app/agents/base_agent.py` for the shared framework; no retrieval,
context, generation, or citation logic lives here.
"""

from __future__ import annotations

from app.agents.base_agent import Advisor

ADVISOR = Advisor(
    advisor_id="ai-engineering",
    display_name="AI Engineering Advisor",
    description=(
        "Advises on AI engineering standards: AI-assisted development, code review, "
        "prompt engineering, and responsible AI practices."
    ),
    persona=(
        "You are the Northstar AI Engineering Advisor, a specialist assistant for questions "
        "about building software with AI assistance at Northstar. You answer using only the "
        "Northstar AI engineering reference material supplied below as numbered sources "
        "([S1], [S2], ...)."
    ),
    structure_guidance="Answer\nEngineering Controls\nRisks or Considerations",
    extra_guidance=(
        "Distinguish which controls apply specifically to AI-generated or AI-assisted work (e.g. "
        "mandatory human review) from general engineering practice, and note the human "
        "accountability requirement for any AI-assisted output."
    ),
    default_filters={"document_id": "NLC-ENG-003"},  # 12_AI_Engineering_Standards.md
)
