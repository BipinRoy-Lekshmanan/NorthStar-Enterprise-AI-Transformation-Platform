"""Shared response envelopes used across every route group (Milestone 7):
the pagination shape and the error shape. No business logic lives here.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

from app.api.errors import ApiError, ErrorCode

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict = {}
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total_items: int
    total_pages: int


def validate_pagination(page: int, page_size: int) -> tuple[int, int]:
    """Fail fast with a clear `ApiError` for out-of-range pagination params."""
    if page < 1:
        raise ApiError(400, ErrorCode.VALIDATION_ERROR, f"page must be >= 1, got {page}.")
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise ApiError(
            400, ErrorCode.VALIDATION_ERROR, f"page_size must be between 1 and {MAX_PAGE_SIZE}, got {page_size}."
        )
    return page, page_size


def paginate_slice(items: list, page: int, page_size: int) -> tuple[list, int, int]:
    """Returns `(page_items, total_items, total_pages)` for `items` sliced
    to `page`/`page_size` (1-indexed page)."""
    total_items = len(items)
    total_pages = max(1, -(-total_items // page_size))  # ceiling division
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end], total_items, total_pages
