"""Security Advisor -- a thin specialization over RagService.

Deliberately ships with **no default retrieval filter**, unlike most
other advisors: Northstar's security guidance is not concentrated in a
single document (Security_Architecture.md is an empty placeholder --
see `enterprise_knowledge_base/03_Architecture/`) but spread across
DevSecOps Standards, AI Engineering Standards' AI Security section, and
elsewhere. A hard document filter here would silently starve retrieval
of relevant content, so this advisor relies on ranking across the whole
index instead. See `app/agents/base_agent.py` for the shared framework.
"""

from __future__ import annotations

from app.agents.base_agent import Advisor

ADVISOR = Advisor(
    advisor_id="security",
    display_name="Security Advisor",
    description=(
        "Advises on security controls across Northstar's engineering standards. Searches "
        "the full knowledge base rather than one document, since security guidance is "
        "distributed across DevSecOps, AI engineering, and architecture material."
    ),
    persona=(
        "You are the Northstar Security Advisor, a specialist assistant for security-related "
        "engineering questions. You answer using only the Northstar reference material supplied "
        "below as numbered sources ([S1], [S2], ...), which may be drawn from multiple documents "
        "since Northstar's security guidance is not concentrated in a single one."
    ),
    structure_guidance="Answer\nSecurity Controls\nResidual Risks",
    extra_guidance=(
        "Never state or imply that an approach is certified secure, compliant, or approved for "
        "production -- describe what the documented controls require and note that a human "
        "security owner must approve any production decision."
    ),
    default_filters={},
    domain_keywords=(
        "security", "vulnerability", "threat", "encryption", "access control",
        "authentication", "authorization", "security control", "credential",
    ),
)
