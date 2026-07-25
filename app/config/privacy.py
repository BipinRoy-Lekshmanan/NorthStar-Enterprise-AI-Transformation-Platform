"""Privacy / data-handling configuration (Milestone 8).

`PrivacySettings.include_citation_excerpts` (default `True`) lets a
deployment disable citation excerpts platform-wide -- when `False`, a
citation still identifies *which* document/section grounded an answer
(`document_id`, title, section, score), it just never echoes back the
source text itself. Wired at the same API-boundary "post-process the
citation list" layer Task #105's classification-based filtering already
established (`app.api.services.knowledge_service.filter_restricted_citations`),
not by touching `app.rag.citation_engine` (Milestone 3) -- the citation
is still built with a real excerpt internally, this only controls
whether that excerpt is ever returned to a caller.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeVar

from app.config.settings import parse_bool

DEFAULT_INCLUDE_CITATION_EXCERPTS = True
REDACTED_EXCERPT = "[excerpt redacted by privacy policy]"

_C = TypeVar("_C")


@dataclass(frozen=True)
class PrivacySettings:
    include_citation_excerpts: bool

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "PrivacySettings":
        env = env if env is not None else os.environ
        return cls(
            include_citation_excerpts=parse_bool(
                env, "INCLUDE_CITATION_EXCERPTS", DEFAULT_INCLUDE_CITATION_EXCERPTS,
            ),
        )


def redact_citation_excerpts(citations: list[_C], include_excerpts: bool) -> list[_C]:
    """No-op when `include_excerpts` is `True` (the default) -- every
    pre-existing caller that never passes a `PrivacySettings` is
    unaffected. Works on either `app.models.citation.Citation` or
    `app.api.schemas.query.CitationOut` -- both are pydantic models with
    an `excerpt` field, so `model_copy(update=...)` works on either."""
    if include_excerpts:
        return citations
    return [citation.model_copy(update={"excerpt": REDACTED_EXCERPT}) for citation in citations]
