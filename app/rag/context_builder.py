"""Converts retrieval results into safe, bounded model context.

Also decides whether the retrieved context is sufficient to answer from --
before any prompt is built or any language model is called. This is the
milestone's core "don't invent an answer from weak context" guardrail:
`RagService` never proceeds to generation when `ContextBuildResult.sufficient`
is False.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.models.chunk import Chunk
from app.models.response import RetrievalResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextBlock:
    """A single retrieved chunk, assigned a stable request-level source id."""

    source_id: str  # "S1", "S2", ...
    chunk: Chunk
    score: float


@dataclass(frozen=True)
class ContextBuildResult:
    blocks: list[ContextBlock]
    excluded_count: int
    excluded_reasons: dict[str, int]
    total_characters: int
    highest_score: float | None
    sufficient: bool
    insufficiency_reason: str | None = None


class ContextBuilder:
    """Rank-preserving, size-bounded, dedup-aware context construction.

    Character-based budget, not token-based -- consistent with Milestone 1's
    chunking (also character-based) and documented as a known limitation
    (different LLM providers tokenize differently; a character budget is a
    conservative proxy that avoids over-committing to one provider's
    tokenizer).
    """

    def __init__(
        self,
        max_characters: int,
        max_chunks: int,
        min_score: float,
        insufficient_min_results: int,
        insufficient_min_score: float,
    ):
        self._max_characters = max_characters
        self._max_chunks = max_chunks
        self._min_score = min_score
        self._insufficient_min_results = insufficient_min_results
        self._insufficient_min_score = insufficient_min_score

    def build(self, results: list[RetrievalResult]) -> ContextBuildResult:
        highest_score = max((r.score for r in results), default=None)

        if len(results) < self._insufficient_min_results:
            return ContextBuildResult(
                blocks=[], excluded_count=len(results), excluded_reasons={},
                total_characters=0, highest_score=highest_score,
                sufficient=False, insufficiency_reason="no_results",
            )

        if highest_score is not None and highest_score < self._insufficient_min_score:
            return ContextBuildResult(
                blocks=[], excluded_count=len(results), excluded_reasons={},
                total_characters=0, highest_score=highest_score,
                sufficient=False, insufficiency_reason="low_relevance",
            )

        blocks: list[ContextBlock] = []
        excluded_reasons: dict[str, int] = {}
        seen_normalized_text: set[str] = set()
        total_characters = 0
        stopped_on_budget = False

        for result in results:
            if stopped_on_budget:
                excluded_reasons["size_limit"] = excluded_reasons.get("size_limit", 0) + 1
                continue

            text = result.chunk.text.strip()
            if not text:
                excluded_reasons["empty_content"] = excluded_reasons.get("empty_content", 0) + 1
                continue

            if result.score < self._min_score:
                excluded_reasons["below_min_score"] = excluded_reasons.get("below_min_score", 0) + 1
                continue

            normalized = " ".join(text.lower().split())
            if normalized in seen_normalized_text:
                excluded_reasons["duplicate"] = excluded_reasons.get("duplicate", 0) + 1
                continue

            if len(blocks) >= self._max_chunks:
                excluded_reasons["chunk_limit"] = excluded_reasons.get("chunk_limit", 0) + 1
                continue

            if total_characters + len(text) > self._max_characters:
                # Stop rather than let a lower-ranked, smaller chunk jump
                # ahead of a higher-ranked one that didn't fit -- keeps
                # ranking order strictly meaningful.
                excluded_reasons["size_limit"] = excluded_reasons.get("size_limit", 0) + 1
                stopped_on_budget = True
                continue

            seen_normalized_text.add(normalized)
            total_characters += len(text)
            blocks.append(ContextBlock(source_id=f"S{len(blocks) + 1}", chunk=result.chunk, score=result.score))

        if not blocks:
            logger.info("Context build produced no usable blocks from %d retrieval result(s)", len(results))
            return ContextBuildResult(
                blocks=[], excluded_count=len(results), excluded_reasons=excluded_reasons,
                total_characters=0, highest_score=highest_score,
                sufficient=False, insufficiency_reason="no_usable_context",
            )

        return ContextBuildResult(
            blocks=blocks,
            excluded_count=len(results) - len(blocks),
            excluded_reasons=excluded_reasons,
            total_characters=total_characters,
            highest_score=highest_score,
            sufficient=True,
            insufficiency_reason=None,
        )
