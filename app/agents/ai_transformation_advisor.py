"""Executive AI Transformation Advisor -- a thin specialization over RagService.

Deliberately ships with **no default retrieval filter**, unlike most
other advisors: "AI Transformation Perspective" content is repeated
across many engineering documents (Incident Management, DevSecOps,
Testing, etc.) in addition to its primary document
(19_AI_SDLC_Transformation.md), so a single document_id filter would
miss most of what an executive-level question needs. See
`app/agents/base_agent.py` for the shared framework.
"""

from __future__ import annotations

from app.agents.base_agent import Advisor

ADVISOR = Advisor(
    advisor_id="executive-ai-transformation",
    display_name="Executive AI Transformation Advisor",
    description=(
        "Advises on Northstar's AI transformation strategy at an executive level. Searches "
        "the full knowledge base, since AI transformation perspective content is spread "
        "across many engineering documents rather than one."
    ),
    persona=(
        "You are the Northstar Executive AI Transformation Advisor, a specialist assistant for "
        "leadership-level questions about Northstar's AI-enabled transformation strategy. You "
        "answer using only the Northstar reference material supplied below as numbered sources "
        "([S1], [S2], ...), which may be drawn from multiple documents, and you frame your answer "
        "for an executive audience rather than an implementation audience."
    ),
    structure_guidance="Answer\nStrategic Recommendation\nOrganizational Risks or Considerations",
    extra_guidance=(
        "Favor organizational, governance, and investment framing over implementation detail; "
        "where the context distinguishes a maturity level or transformation phase, state which "
        "one the answer applies to."
    ),
    default_filters={},
    domain_keywords=(
        "ai transformation", "ai strategy", "executive", "maturity", "roi",
        "organizational", "governance", "transformation roadmap",
    ),
)
