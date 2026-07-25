"""Usage/cost tracking + daily budget enforcement (Milestone 8).

Every tracked call becomes one `usage_events` row
(`app.db.models.UsageEvent`). Budgets are evaluated against the rolling
sum of `cost_usd` for events within the current UTC calendar day --
deliberately simple (no sliding window, no per-user budgets, no
carryover) to match this milestone's "operational maturity, not a
billing platform" scope.

`cost_usd` is `None` whenever `app.telemetry.token_usage.estimate_cost_usd`
doesn't recognize the `(provider, model)` pair (e.g. the `fake`
provider) -- such events are still recorded (for token-count
observability) but never counted toward a budget, since a `None` cost
would otherwise either silently zero out or crash the budget sum.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker

from app.db.engine import session_scope
from app.db.models import UsageEvent
from app.telemetry.token_usage import estimate_cost_usd


class BudgetExceededError(Exception):
    """Raised by `CostTracker.enforce_budget()` when today's spend has
    already reached the configured daily budget."""

    def __init__(self, spent_usd: float, budget_usd: float):
        super().__init__(f"Daily budget exceeded: ${spent_usd:.4f} spent of ${budget_usd:.4f} budget.")
        self.spent_usd = spent_usd
        self.budget_usd = budget_usd


@dataclass(frozen=True)
class BudgetStatus:
    spent_usd: float
    budget_usd: float | None
    warning_threshold_usd: float | None
    warning: bool
    exceeded: bool


class CostTracker:
    def __init__(
        self, session_factory: sessionmaker[Session], *,
        daily_budget_usd: float | None = None, warning_ratio: float = 0.8,
    ):
        self._session_factory = session_factory
        self._daily_budget_usd = daily_budget_usd
        self._warning_ratio = warning_ratio

    def record_usage(
        self, *, provider: str, model: str, operation: str, input_tokens: int | None = None,
        output_tokens: int | None = None, actor: str | None = None, request_id: str | None = None,
    ) -> float | None:
        cost_usd = estimate_cost_usd(provider, model, input_tokens, output_tokens)
        with session_scope(self._session_factory) as session:
            session.add(
                UsageEvent(
                    event_id=str(uuid.uuid4()), timestamp=datetime.now(timezone.utc), actor=actor,
                    provider=provider, model=model, operation=operation,
                    input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd,
                    request_id=request_id,
                )
            )
        return cost_usd

    def get_daily_spend_usd(self, day: date | None = None) -> float:
        day = day or datetime.now(timezone.utc).date()
        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        with session_scope(self._session_factory) as session:
            total = (
                session.query(func.coalesce(func.sum(UsageEvent.cost_usd), 0.0))
                .filter(UsageEvent.timestamp >= start, UsageEvent.timestamp < end)
                .scalar()
            )
        return float(total or 0.0)

    def check_budget(self) -> BudgetStatus:
        spent = self.get_daily_spend_usd()
        if self._daily_budget_usd is None:
            return BudgetStatus(
                spent_usd=spent, budget_usd=None, warning_threshold_usd=None, warning=False, exceeded=False,
            )
        warning_threshold = self._daily_budget_usd * self._warning_ratio
        return BudgetStatus(
            spent_usd=spent, budget_usd=self._daily_budget_usd, warning_threshold_usd=warning_threshold,
            warning=spent >= warning_threshold, exceeded=spent >= self._daily_budget_usd,
        )

    def enforce_budget(self) -> BudgetStatus:
        """Raises `BudgetExceededError` if today's spend has already
        reached the configured budget -- called before a paid call, not
        after, so the call that would tip things over never happens."""
        status = self.check_budget()
        if status.exceeded:
            raise BudgetExceededError(status.spent_usd, status.budget_usd)  # type: ignore[arg-type]
        return status
