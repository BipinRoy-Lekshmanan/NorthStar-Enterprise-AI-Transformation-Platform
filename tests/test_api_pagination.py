"""Tests for `app.api.schemas.common` -- the pagination envelope and
its validation/slicing helpers (Milestone 7).
"""

import pytest

from app.api.errors import ApiError
from app.api.schemas.common import MAX_PAGE_SIZE, paginate_slice, validate_pagination


def test_validate_pagination_accepts_valid_values():
    assert validate_pagination(1, 25) == (1, 25)
    assert validate_pagination(3, MAX_PAGE_SIZE) == (3, MAX_PAGE_SIZE)


def test_validate_pagination_rejects_page_below_one():
    with pytest.raises(ApiError) as exc_info:
        validate_pagination(0, 25)
    assert exc_info.value.status_code == 400


def test_validate_pagination_rejects_oversized_page_size():
    with pytest.raises(ApiError) as exc_info:
        validate_pagination(1, MAX_PAGE_SIZE + 1)
    assert exc_info.value.status_code == 400


def test_paginate_slice_returns_correct_page_and_totals():
    items = list(range(1, 51))  # 50 items

    page_items, total_items, total_pages = paginate_slice(items, page=1, page_size=20)
    assert page_items == list(range(1, 21))
    assert total_items == 50
    assert total_pages == 3

    page_items_2, _, _ = paginate_slice(items, page=2, page_size=20)
    assert page_items_2 == list(range(21, 41))

    page_items_3, _, _ = paginate_slice(items, page=3, page_size=20)
    assert page_items_3 == list(range(41, 51))


def test_paginate_slice_out_of_range_page_returns_empty():
    items = list(range(1, 11))
    page_items, total_items, total_pages = paginate_slice(items, page=5, page_size=10)
    assert page_items == []
    assert total_items == 10
    assert total_pages == 1


def test_paginate_slice_empty_items_returns_one_total_page():
    page_items, total_items, total_pages = paginate_slice([], page=1, page_size=25)
    assert page_items == []
    assert total_items == 0
    assert total_pages == 1
