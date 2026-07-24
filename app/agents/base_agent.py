"""Shared Advisor framework.

Each domain advisor (see `app/agents/*_advisor.py`) is a thin,
declarative specialization over the existing `RagService`: a persona,
optional default retrieval filters, and a response structure / extra
domain guidance layered on top of the exact same shared grounding
guardrails every advisor gets for free
(`app.config.prompt_config.GROUNDING_GUARDRAILS`). No retrieval, context
construction, generation, or citation logic is duplicated or
reimplemented here -- `Advisor.ask()` calls straight through to
`RagService.ask()`, which is untouched Milestone 1-3 infrastructure.

This module deliberately does not know about routing, orchestration, or
which advisor to pick for a question -- see `app/agents/registry.py` for
lookup, and `app/rag/ask.py --advisor` for CLI selection. Choosing
*between* advisors automatically is out of scope for this milestone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.config.prompt_config import PROMPT_VERSION, RagPrompt, build_system_prompt
from app.models.response import RagAnswer
from app.rag.context_builder import ContextBuildResult
from app.rag.pipeline import RagService


@dataclass(frozen=True)
class Advisor:
    advisor_id: str
    display_name: str
    description: str
    persona: str
    structure_guidance: str
    extra_guidance: str | None = None
    default_filters: dict[str, str] = field(default_factory=dict)
    domain_keywords: tuple[str, ...] = ()
    """Terms used only by `app.agents.router.AdvisorRouter`'s keyword
    signal -- never affects retrieval, prompts, or `.ask()`. Optional and
    additive: an advisor with no keywords simply contributes nothing to
    that signal."""

    @property
    def system_prompt(self) -> str:
        return build_system_prompt(self.persona, self.structure_guidance, self.extra_guidance)

    @property
    def prompt_version(self) -> str:
        return f"{PROMPT_VERSION}+{self.advisor_id}-v1"

    def ask(
        self,
        service: RagService,
        question: str,
        *,
        top_k: int | None = None,
        filters: dict[str, str] | None = None,
        on_context_built: Callable[[ContextBuildResult], None] | None = None,
        on_prompt_built: Callable[[RagPrompt], None] | None = None,
    ) -> RagAnswer:
        """Ask this advisor a question via `service`.

        `filters` (if given) are merged on top of `default_filters`,
        with caller-supplied keys taking precedence -- an explicit
        request always wins over the advisor's soft default.
        """
        merged_filters = {**self.default_filters, **(filters or {})}
        return service.ask(
            question,
            top_k=top_k,
            filters=merged_filters,
            system_prompt=self.system_prompt,
            prompt_version=self.prompt_version,
            on_context_built=on_context_built,
            on_prompt_built=on_prompt_built,
        )
