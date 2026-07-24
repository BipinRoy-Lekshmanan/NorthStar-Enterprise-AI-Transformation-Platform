"""Static advisor registry.

An explicit tuple of the 8 `Advisor` instances, not dynamic
plugin-discovery -- auditable at a glance, and adding a 9th advisor is
"write one file + one line here." No routing, ranking, or automatic
advisor selection lives here (or anywhere in this milestone) -- callers
(the CLI, or a future caller) pick an advisor explicitly by id.
"""

from __future__ import annotations

from app.agents.ai_engineering_advisor import ADVISOR as AI_ENGINEERING_ADVISOR
from app.agents.ai_transformation_advisor import ADVISOR as EXECUTIVE_AI_TRANSFORMATION_ADVISOR
from app.agents.architecture_advisor import ADVISOR as ARCHITECTURE_ADVISOR
from app.agents.base_agent import Advisor
from app.agents.devsecops_advisor import ADVISOR as DEVSECOPS_ADVISOR
from app.agents.incident_advisor import ADVISOR as INCIDENT_MANAGEMENT_ADVISOR
from app.agents.platform_advisor import ADVISOR as PLATFORM_ENGINEERING_ADVISOR
from app.agents.security_advisor import ADVISOR as SECURITY_ADVISOR
from app.agents.testing_advisor import ADVISOR as TESTING_ADVISOR

_ADVISORS: tuple[Advisor, ...] = (
    ARCHITECTURE_ADVISOR,
    AI_ENGINEERING_ADVISOR,
    DEVSECOPS_ADVISOR,
    TESTING_ADVISOR,
    SECURITY_ADVISOR,
    PLATFORM_ENGINEERING_ADVISOR,
    INCIDENT_MANAGEMENT_ADVISOR,
    EXECUTIVE_AI_TRANSFORMATION_ADVISOR,
)

ADVISOR_REGISTRY: dict[str, Advisor] = {advisor.advisor_id: advisor for advisor in _ADVISORS}


class UnknownAdvisorError(KeyError):
    """Raised when an advisor id doesn't match any registered advisor."""


def get_advisor(advisor_id: str) -> Advisor:
    try:
        return ADVISOR_REGISTRY[advisor_id]
    except KeyError:
        available = ", ".join(sorted(ADVISOR_REGISTRY))
        raise UnknownAdvisorError(f"Unknown advisor '{advisor_id}'. Available: {available}") from None


def list_advisors() -> list[Advisor]:
    return list(_ADVISORS)
