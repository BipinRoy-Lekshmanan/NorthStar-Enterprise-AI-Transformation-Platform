"""Milestone 8's operational SQLite store (SQLAlchemy + Alembic).

Scope: `audit_events`, `idempotency_records`, `operations`, and
`usage_events` -- genuinely new Milestone 8 concerns with no prior
persistence layer. `WorkflowStore`/`EvaluationRunStore` (Milestone 6/7)
are untouched, tested, atomic-write JSON-file stores.
"""
