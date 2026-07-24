"""Parses and validates `[S#]` citations out of a generated answer.

Deterministic syntax validation only -- this milestone does not attempt
semantic verification that a cited source actually supports the claim
next to it. Citations are only ever built for ids the model actually
referenced; an id present in the context but never cited never becomes a
`Citation`, and an id the model invents (not in the context) is dropped
with a warning rather than silently accepted.
"""

from __future__ import annotations

import logging
import re

from app.models.citation import Citation
from app.rag.context_builder import ContextBlock

logger = logging.getLogger(__name__)

_CITATION_PATTERN = re.compile(r"\[S(\d+)\]")
_DEFAULT_EXCERPT_LENGTH = 240


def parse_citation_ids(answer_text: str, valid_ids: set[str]) -> tuple[list[str], list[str]]:
    """Extract cited source ids from `answer_text`.

    Returns `(valid_ids_in_first_use_order, warnings)`. Duplicate
    citations are collapsed to their first occurrence; ids not present in
    `valid_ids` are excluded from the result and reported as a warning
    rather than silently kept or silently dropped.
    """
    found = [f"S{match.group(1)}" for match in _CITATION_PATTERN.finditer(answer_text)]
    ordered_unique = list(dict.fromkeys(found))

    valid = [cid for cid in ordered_unique if cid in valid_ids]
    invalid = [cid for cid in ordered_unique if cid not in valid_ids]

    warnings: list[str] = []
    if not ordered_unique:
        warnings.append("Model did not cite any source.")
    if invalid:
        warnings.append(f"Model cited unknown source identifier(s): {', '.join(invalid)}.")
        logger.warning("Citation validation: unknown source id(s) %s in generated answer", invalid)

    return valid, warnings


def build_citations(
    cited_ids: list[str], context_blocks: list[ContextBlock], excerpt_length: int = _DEFAULT_EXCERPT_LENGTH
) -> list[Citation]:
    """Build structured `Citation` objects for exactly the ids the model cited."""
    blocks_by_id = {block.source_id: block for block in context_blocks}

    citations: list[Citation] = []
    for source_id in cited_ids:
        block = blocks_by_id.get(source_id)
        if block is None:
            continue  # already reported as a warning by parse_citation_ids

        chunk = block.chunk
        text = chunk.text.strip()
        excerpt = text if len(text) <= excerpt_length else text[:excerpt_length].rstrip() + "..."

        citations.append(
            Citation(
                source_id=source_id,
                chunk_id=chunk.chunk_id,
                document_title=chunk.document_title,
                document_id=chunk.document_id,
                source_file=chunk.source_file,
                source_path=chunk.source_path,
                section_title=chunk.section_title,
                heading_path=chunk.heading_path,
                score=block.score,
                excerpt=excerpt,
            )
        )
    return citations
