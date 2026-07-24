"""Extracts YAML frontmatter metadata and heading structure from Markdown text.

Reused by both the document loader (document-level metadata) and the
chunker (section heading hierarchy), so frontmatter/heading parsing lives
in exactly one place.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import yaml

from app.models.document import DocumentMetadata

logger = logging.getLogger(__name__)

_FRONTMATTER_PATTERN = re.compile(r"\A---[ \t]*\n(.*?\n)^---[ \t]*\n?", re.DOTALL | re.MULTILINE)
_HEADING_PATTERN = re.compile(r"^(#{1,6})[ \t]+(\S.*?)\s*$", re.MULTILINE)

# Frontmatter keys mapped explicitly onto DocumentMetadata fields.
_KNOWN_FIELDS = (
    "document_id",
    "title",
    "owner",
    "version",
    "status",
    "classification",
    "review_cycle",
    "effective_date",
)


@dataclass(frozen=True)
class Heading:
    """A single Markdown heading and its character span within the document body."""

    level: int
    text: str
    start: int
    body_start: int  # offset where content belonging to this heading begins


def split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Split leading YAML frontmatter (delimited by ``---`` lines) from the body.

    Returns an empty dict and the original content unchanged when no valid
    frontmatter block is present -- malformed frontmatter is logged and
    treated as absent rather than raised, so one bad document never aborts
    the run.
    """
    match = _FRONTMATTER_PATTERN.match(content)
    if not match:
        return {}, content

    body = content[match.end():]
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        logger.warning("Malformed YAML frontmatter, ignoring: %s", exc)
        return {}, content

    if not isinstance(data, dict):
        logger.warning("Frontmatter did not parse to a mapping, ignoring")
        return {}, content

    return data, body


def extract_headings(body: str) -> list[Heading]:
    """Return every ATX-style heading (``#`` .. ``######``) in document order."""
    headings: list[Heading] = []
    matches = list(_HEADING_PATTERN.finditer(body))
    for i, m in enumerate(matches):
        body_start = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        headings.append(
            Heading(level=len(m.group(1)), text=m.group(2).strip(), start=m.start(), body_start=body_start)
        )
    return headings


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def extract_metadata(content: str, source_path: str) -> DocumentMetadata:
    """Build a :class:`DocumentMetadata` from a document's raw content.

    Falls back to the first heading for ``title`` when frontmatter omits it
    (or is absent entirely), since several knowledge-base documents --
    e.g. README stubs and Engineering Organization -- have no frontmatter.
    """
    frontmatter, body = split_frontmatter(content)

    known = {key: frontmatter[key] for key in _KNOWN_FIELDS if frontmatter.get(key) is not None}
    known = {key: str(value) for key, value in known.items()}

    title = known.get("title")
    if not title:
        headings = extract_headings(body)
        if headings:
            title = headings[0].text
        else:
            logger.info("No title in frontmatter or headings for %s", source_path)

    extra = {
        key: value
        for key, value in frontmatter.items()
        if key not in _KNOWN_FIELDS and key != "related_documents"
    }

    return DocumentMetadata(
        document_id=known.get("document_id"),
        title=title,
        owner=known.get("owner"),
        version=known.get("version"),
        status=known.get("status"),
        classification=known.get("classification"),
        review_cycle=known.get("review_cycle"),
        effective_date=known.get("effective_date"),
        related_documents=_coerce_str_list(frontmatter.get("related_documents")),
        extra=extra,
    )
