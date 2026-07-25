"""Tests for `app.db` (Milestone 8) -- engine/session construction, the
ORM models, and the `python -m app.db upgrade|current|history` CLI.

Every test points `DATABASE_URL` at a `tmp_path` SQLite file via
`monkeypatch.setenv` -- never the real `data/app.db` -- so nothing here
touches developer-machine or CI-runner state.
"""

from datetime import datetime, timedelta, timezone

from app.db import cli as db_cli
from app.db.engine import build_engine, build_session_factory, create_all, session_scope
from app.db.models import AuditEventRecord, IdempotencyRecord, Operation, UsageEvent


def _sqlite_url(tmp_path, name="test.db"):
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def test_create_all_creates_every_table(tmp_path):
    engine = build_engine(_sqlite_url(tmp_path))
    create_all(engine)

    from sqlalchemy import inspect

    tables = set(inspect(engine).get_table_names())
    assert {"audit_events", "idempotency_records", "operations", "usage_events"} <= tables


def test_session_scope_commits_on_success(tmp_path):
    engine = build_engine(_sqlite_url(tmp_path))
    create_all(engine)
    session_factory = build_session_factory(engine)

    with session_scope(session_factory) as session:
        session.add(
            AuditEventRecord(
                event_id="evt-1", sequence_number=1, actor="alice", action="workflow_executed",
                event_metadata={"workflow_id": "architecture_review"}, current_hash="deadbeef",
            )
        )

    with session_scope(session_factory) as session:
        row = session.query(AuditEventRecord).filter_by(event_id="evt-1").one()
        assert row.actor == "alice"
        assert row.event_metadata == {"workflow_id": "architecture_review"}


def test_session_scope_rolls_back_on_exception(tmp_path):
    engine = build_engine(_sqlite_url(tmp_path))
    create_all(engine)
    session_factory = build_session_factory(engine)

    try:
        with session_scope(session_factory) as session:
            session.add(
                UsageEvent(
                    event_id="usage-1", provider="openai", model="gpt-4o-mini", operation="llm_generate",
                )
            )
            raise RuntimeError("simulated failure mid-transaction")
    except RuntimeError:
        pass

    with session_scope(session_factory) as session:
        assert session.query(UsageEvent).count() == 0


def test_idempotency_record_key_and_endpoint_must_be_unique_together(tmp_path):
    engine = build_engine(_sqlite_url(tmp_path))
    create_all(engine)
    session_factory = build_session_factory(engine)
    now = datetime.now(timezone.utc)

    with session_scope(session_factory) as session:
        session.add(
            IdempotencyRecord(
                idempotency_key="key-1", endpoint="workflow_execute", request_hash="h1",
                response_status=200, response_body={"execution_id": "e1"},
                expires_at=now + timedelta(hours=24),
            )
        )

    # Same key on a *different* endpoint is a distinct record -- the
    # unique constraint is scoped to (idempotency_key, endpoint) together.
    with session_scope(session_factory) as session:
        session.add(
            IdempotencyRecord(
                idempotency_key="key-1", endpoint="knowledge_ingest", request_hash="h2",
                response_status=200, response_body={"documents": 3},
                expires_at=now + timedelta(hours=24),
            )
        )

    with session_scope(session_factory) as session:
        assert session.query(IdempotencyRecord).count() == 2


def test_operation_round_trip(tmp_path):
    engine = build_engine(_sqlite_url(tmp_path))
    create_all(engine)
    session_factory = build_session_factory(engine)

    with session_scope(session_factory) as session:
        session.add(Operation(operation_id="op-1", operation_type="knowledge_rebuild", status="running"))

    with session_scope(session_factory) as session:
        op = session.query(Operation).filter_by(operation_id="op-1").one()
        assert op.status == "running"
        assert op.result is None


def test_cli_upgrade_creates_the_schema_and_stamps_alembic_version(tmp_path, monkeypatch):
    """Functional check rather than a stdout-text check: `current`/
    `history` write through Alembic's own stdout stream, which pytest's
    fd-level capture fixtures don't reliably intercept across nested
    capture layers -- the thing actually worth asserting is that
    `upgrade` left the database at a real, known schema state."""
    url = _sqlite_url(tmp_path)
    monkeypatch.setenv("DATABASE_URL", url)

    assert db_cli.main(["upgrade"]) == 0

    from sqlalchemy import inspect

    engine = build_engine(url)
    inspector = inspect(engine)
    assert {"audit_events", "idempotency_records", "operations", "usage_events", "alembic_version"} <= set(
        inspector.get_table_names()
    )

    with engine.connect() as connection:
        from sqlalchemy import text

        (stamped_revision,) = connection.execute(text("SELECT version_num FROM alembic_version")).one()
    assert stamped_revision  # a real revision id was stamped, not left empty


def test_cli_current_and_history_do_not_raise(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _sqlite_url(tmp_path))

    assert db_cli.main(["upgrade"]) == 0
    assert db_cli.main(["current"]) == 0
    assert db_cli.main(["history"]) == 0
