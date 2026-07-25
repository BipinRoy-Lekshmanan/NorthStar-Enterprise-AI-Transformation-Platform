"""Tests for `app.telemetry.cost_tracker.CostTracker` (Milestone 8)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.db.engine import build_engine, build_session_factory, create_all, session_scope
from app.db.models import UsageEvent
from app.telemetry.cost_tracker import BudgetExceededError, CostTracker


def _tracker(tmp_path, **kwargs) -> CostTracker:
    engine = build_engine(f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    create_all(engine)
    return CostTracker(build_session_factory(engine), **kwargs)


def test_record_usage_persists_a_usage_event_with_estimated_cost(tmp_path):
    tracker = _tracker(tmp_path)
    cost = tracker.record_usage(
        provider="openai", model="gpt-4o-mini", operation="llm_generate",
        input_tokens=1_000_000, output_tokens=1_000_000, actor="alice", request_id="req-1",
    )
    assert cost == pytest.approx(0.75)
    assert tracker.get_daily_spend_usd() == pytest.approx(0.75)


def test_record_usage_for_an_unpriced_model_still_persists_with_null_cost(tmp_path):
    tracker = _tracker(tmp_path)
    cost = tracker.record_usage(
        provider="fake", model="fake-echo-v1", operation="llm_generate",
        input_tokens=100, output_tokens=50,
    )
    assert cost is None
    assert tracker.get_daily_spend_usd() == 0.0  # null cost never counts toward spend


def test_get_daily_spend_only_counts_todays_events(tmp_path):
    tracker = _tracker(tmp_path)
    tracker.record_usage(provider="openai", model="gpt-4o-mini", operation="llm_generate", input_tokens=1_000_000)

    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    with session_scope(tracker._session_factory) as session:  # noqa: SLF001
        session.add(
            UsageEvent(
                event_id="old-event", timestamp=datetime.now(timezone.utc) - timedelta(days=1),
                provider="openai", model="gpt-4o-mini", operation="llm_generate", cost_usd=999.0,
            )
        )

    today_spend = tracker.get_daily_spend_usd()
    yesterday_spend = tracker.get_daily_spend_usd(yesterday)
    assert today_spend == pytest.approx(0.15)
    assert yesterday_spend == pytest.approx(999.0)


def test_check_budget_with_no_budget_configured_is_never_exceeded(tmp_path):
    tracker = _tracker(tmp_path, daily_budget_usd=None)
    tracker.record_usage(provider="openai", model="gpt-4o", operation="llm_generate", input_tokens=10_000_000)

    status = tracker.check_budget()
    assert status.budget_usd is None
    assert status.exceeded is False
    assert status.warning is False


def test_check_budget_warns_at_the_configured_ratio(tmp_path):
    tracker = _tracker(tmp_path, daily_budget_usd=1.0, warning_ratio=0.5)
    # 1M input tokens on gpt-4o-mini = $0.15 -- under the $0.50 warning threshold.
    tracker.record_usage(provider="openai", model="gpt-4o-mini", operation="llm_generate", input_tokens=1_000_000)
    assert tracker.check_budget().warning is False

    # Push spend past the 50% warning threshold ($0.50) but not the $1.00 budget.
    tracker.record_usage(provider="openai", model="gpt-4o-mini", operation="llm_generate", input_tokens=3_000_000)
    status = tracker.check_budget()
    assert status.spent_usd == pytest.approx(0.6)
    assert status.warning is True
    assert status.exceeded is False


def test_check_budget_reports_exceeded_once_spend_reaches_the_budget(tmp_path):
    tracker = _tracker(tmp_path, daily_budget_usd=0.1)
    tracker.record_usage(provider="openai", model="gpt-4o-mini", operation="llm_generate", input_tokens=1_000_000)

    status = tracker.check_budget()
    assert status.exceeded is True


def test_enforce_budget_raises_once_exceeded(tmp_path):
    tracker = _tracker(tmp_path, daily_budget_usd=0.1)
    tracker.record_usage(provider="openai", model="gpt-4o-mini", operation="llm_generate", input_tokens=1_000_000)

    with pytest.raises(BudgetExceededError):
        tracker.enforce_budget()


def test_enforce_budget_does_not_raise_when_under_budget(tmp_path):
    tracker = _tracker(tmp_path, daily_budget_usd=100.0)
    tracker.record_usage(provider="openai", model="gpt-4o-mini", operation="llm_generate", input_tokens=1_000_000)

    status = tracker.enforce_budget()
    assert status.exceeded is False
