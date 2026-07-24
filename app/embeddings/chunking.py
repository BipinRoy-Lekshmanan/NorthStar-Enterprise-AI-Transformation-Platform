"""Markdown-aware chunking.

Splits a loaded document primarily along its heading structure (so every
chunk carries an accurate heading path), merges fragments that are too
small to be useful on their own, and -- only for sections that still
exceed ``chunk_size`` -- falls back to a size-bounded split that prefers
paragraph boundaries and tries to avoid breaking a Markdown table midway.

This module intentionally does not depend on any embedding library: it
produces plain-text chunks that a future embedding step can consume.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.config.settings import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE
from app.ingestion.metadata_extractor import extract_headings, split_frontmatter
from app.models.chunk import Chunk
from app.models.document import LoadedDocument

_BLANK_LINE_PATTERN = re.compile(r"\n[ \t]*\n")


@dataclass(frozen=True)
class _Segment:
    """An intermediate heading-bounded slice of a document, pre-size-splitting."""

    heading_path: list[str]
    section_title: str | None
    text: str


class MarkdownChunker:
    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        min_chunk_chars: int | None = None,
    ):
        if chunk_size <= 0:
            raise ValueError(f"chunk_size must be positive, got {chunk_size}")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError(
                f"chunk_overlap ({chunk_overlap}) must be >= 0 and < chunk_size ({chunk_size})"
            )
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        # Segments smaller than this are folded into a neighbor rather than
        # emitted as their own (near-empty) chunk.
        self._min_chunk_chars = min_chunk_chars or max(100, chunk_size // 6)

    def chunk(self, document: LoadedDocument) -> list[Chunk]:
        """Chunk a loaded document, returning chunks in document order."""
        _, body = split_frontmatter(document.content)
        segments = self._build_segments(body)
        segments = self._merge_small_segments(segments)

        chunks: list[Chunk] = []
        index = 0
        for segment in segments:
            for piece in self._split_segment_text(segment.text):
                piece = piece.strip()
                if not piece:
                    continue
                chunks.append(
                    Chunk(
                        chunk_id=_make_chunk_id(document.source_path, index, piece),
                        text=piece,
                        chunk_index=index,
                        document_title=document.metadata.title,
                        document_id=document.metadata.document_id,
                        source_file=document.source_file,
                        source_path=document.source_path,
                        section_title=segment.section_title,
                        heading_path=segment.heading_path,
                        content_hash=document.content_hash,
                        char_count=len(piece),
                    )
                )
                index += 1
        return chunks

    # -- heading-based segmentation -------------------------------------------------

    @staticmethod
    def _build_segments(body: str) -> list[_Segment]:
        headings = extract_headings(body)

        if not headings:
            stripped = body.strip()
            return [_Segment([], None, stripped)] if stripped else []

        segments: list[_Segment] = []

        preamble = body[: headings[0].start].strip()
        if preamble:
            segments.append(_Segment([], None, preamble))

        stack: list[tuple[int, str]] = []
        for i, heading in enumerate(headings):
            while stack and stack[-1][0] >= heading.level:
                stack.pop()
            stack.append((heading.level, heading.text))
            heading_path = [text for _, text in stack]

            end = headings[i + 1].start if i + 1 < len(headings) else len(body)
            text = body[heading.start : end].strip()
            if text:
                segments.append(_Segment(heading_path, heading.text, text))

        return segments

    def _merge_small_segments(self, segments: list[_Segment]) -> list[_Segment]:
        """Fold runs of undersized segments together so no fragment stands alone.

        Consecutive segments accumulate into a group until the group's
        combined length reaches `_min_chunk_chars`; a trailing group that
        never reaches it is folded into the previous group instead. Each
        merged group takes the heading identity of its largest contributor
        (not simply the first or last), since that's the section the
        combined text is actually mostly about.
        """
        if not segments:
            return []

        groups: list[list[_Segment]] = []
        current: list[_Segment] = []
        current_len = 0

        for segment in segments:
            current.append(segment)
            current_len += len(segment.text)
            if current_len >= self._min_chunk_chars:
                groups.append(current)
                current, current_len = [], 0

        if current:
            if groups:
                groups[-1].extend(current)
            else:
                groups.append(current)

        merged: list[_Segment] = []
        for group in groups:
            identity = max(group, key=lambda s: len(s.text))
            merged.append(
                _Segment(
                    heading_path=identity.heading_path,
                    section_title=identity.section_title,
                    text="\n\n".join(s.text for s in group),
                )
            )
        return merged

    # -- size-bounded splitting for oversized sections -------------------------------

    def _split_segment_text(self, text: str) -> list[str]:
        if len(text) <= self._chunk_size:
            return [text]

        pieces: list[str] = []
        pos = 0
        length = len(text)
        min_slice = max(1, self._chunk_size // 5)

        while pos < length:
            target_end = min(pos + self._chunk_size, length)
            if target_end >= length:
                pieces.append(text[pos:length])
                break

            split_at = self._find_split_point(text, pos, target_end, min_slice)
            pieces.append(text[pos:split_at])

            next_pos = split_at - self._chunk_overlap
            pos = next_pos if next_pos > pos else split_at

        return pieces

    def _find_split_point(self, text: str, pos: int, target_end: int, min_slice: int) -> int:
        window_start = max(pos + min_slice, target_end - self._chunk_size // 3)
        window = text[window_start:target_end]

        candidates = [window_start + m.end() for m in _BLANK_LINE_PATTERN.finditer(window)]
        if candidates:
            split_at = candidates[-1]
        else:
            newline = text.rfind("\n", pos + min_slice, target_end)
            split_at = newline + 1 if newline != -1 else target_end

        split_at = self._avoid_table_cut(text, pos, split_at, target_end)
        return max(split_at, pos + 1)

    def _avoid_table_cut(self, text: str, pos: int, split_at: int, target_end: int) -> int:
        """Nudge a split point past a Markdown table block, within a size budget.

        Best-effort only: if the table extends well beyond the budget, the
        original split point is kept rather than producing an oversized chunk.
        """
        line_start = text.rfind("\n", pos, split_at) + 1
        preceding_line = text[line_start:split_at].strip()
        if not preceding_line.startswith("|"):
            return split_at

        slack = self._chunk_size // 4
        search_end = min(len(text), target_end + slack)
        cursor = split_at
        while cursor < search_end:
            next_newline = text.find("\n", cursor)
            end_of_line = next_newline if next_newline != -1 else len(text)
            line = text[cursor:end_of_line].strip()
            if not line.startswith("|"):
                return cursor
            if next_newline == -1:
                return len(text)
            cursor = next_newline + 1

        return split_at


def _make_chunk_id(source_path: str, chunk_index: int, text: str) -> str:
    """A stable, content-addressed chunk id: identical (path, index, text) -> identical id."""
    digest = hashlib.sha256(f"{source_path}::{chunk_index}::{text}".encode("utf-8")).hexdigest()
    return digest[:16]
