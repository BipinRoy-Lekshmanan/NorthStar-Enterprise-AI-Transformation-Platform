"""Typed model for a retrieval query.

Deliberately just "a question to retrieve chunks for" -- no conversation
history, no answer-generation options. Those belong to a future milestone.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RetrievalQuery(BaseModel):
    text: str
    top_k: int = 5
    # Optional exact-match filters over Chunk fields, e.g. {"document_id": "NLC-ENG-007"}.
    filters: dict[str, str] = Field(default_factory=dict)
