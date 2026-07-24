"""Advisor listing/detail/routing application service (Milestone 7).

Thin facade over `app.agents.registry` and `app.agents.router` -- no
retrieval, prompt, or model-provider logic lives here. Directly querying
one named advisor reuses `app.api.services.query_service.ask_manual`
directly (it already does exactly "ask one named advisor"); no separate
wrapper is needed for that specific action.
"""

from __future__ import annotations

from app.agents.base_agent import Advisor
from app.agents.registry import get_advisor, list_advisors
from app.agents.router import AdvisorRouter, RoutingDecision
from app.config.settings import RouterSettings
from app.rag.pipeline import RagService


def list_all_advisors() -> list[Advisor]:
    return list_advisors()


def get_advisor_detail(advisor_id: str) -> Advisor:
    """Raises `UnknownAdvisorError` (mapped to 404 by `app.api.errors`)
    for an unrecognized `advisor_id`."""
    return get_advisor(advisor_id)


def preview_routing(service: RagService, router_settings: RouterSettings, question: str) -> RoutingDecision:
    """Runs the deterministic router (Milestone 5) without executing any
    advisor -- lets a caller see what would be selected before committing
    to a full (LLM-calling) query."""
    router = AdvisorRouter(service.retriever, list_advisors(), router_settings)
    return router.route(question)
