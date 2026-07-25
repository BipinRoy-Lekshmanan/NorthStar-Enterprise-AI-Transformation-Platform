"""Tests for `app.audit` -- the audit event model, the SQLite-backed
hash-chained store (Milestone 8, superseding Milestone 7's JSONL file),
and the `record_event`/`record_from_context` helpers.
"""

from app.audit.logger import AuditContext, record_event, record_from_context
from app.audit.models import AuditEvent
from app.audit.store import AuditStore
from app.db.engine import build_engine, build_session_factory, create_all


def _store(tmp_path, name="audit.db") -> AuditStore:
    engine = build_engine(f"sqlite:///{(tmp_path / name).as_posix()}")
    create_all(engine)
    return AuditStore(build_session_factory(engine))


def test_audit_event_organization_id_defaults_to_none():
    # Multi-tenant boundary prep (Milestone 8) -- always None today.
    event = AuditEvent(actor="alice", role="viewer", action="grounded_question_asked")
    assert event.organization_id is None


def test_audit_event_defaults():
    event = AuditEvent(actor="alice", role="viewer", action="grounded_question_asked")
    assert event.outcome == "success"
    assert event.metadata == {}
    assert event.resource_type is None
    assert event.timestamp is not None


def test_store_records_and_lists_events(tmp_path):
    store = _store(tmp_path)
    record_event(store, actor="alice", role="viewer", action="grounded_question_asked", resource_type="advisor", resource_id="testing")
    record_event(store, actor="bob", role="administrator", action="ingestion_run")

    events = store.list_events()
    assert len(events) == 2
    # most-recent-first
    assert events[0].actor == "bob"
    assert events[0].action == "ingestion_run"
    assert events[1].actor == "alice"
    assert events[1].resource_id == "testing"


def test_store_list_events_respects_limit(tmp_path):
    store = _store(tmp_path)
    for i in range(5):
        record_event(store, actor=f"user{i}", role="viewer", action="grounded_question_asked")

    events = store.list_events(limit=2)
    assert len(events) == 2
    assert events[0].actor == "user4"
    assert events[1].actor == "user3"


def test_store_returns_empty_list_when_no_events_recorded(tmp_path):
    store = _store(tmp_path)
    assert store.list_events() == []


def test_from_env_creates_the_database_file_if_missing(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "app.db"
    assert not target.exists()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{target.as_posix()}")

    store = AuditStore.from_env()
    store.record(AuditEvent(actor="alice", role="viewer", action="grounded_question_asked"))

    assert target.exists()


def test_metadata_never_contains_secrets_by_construction(tmp_path):
    # This is a design-level check: record_event's signature only accepts a
    # plain metadata dict the caller controls -- there is no path for a full
    # prompt, answer, or API key to be captured automatically.
    store = _store(tmp_path)
    record_event(
        store, actor="alice", role="viewer", action="grounded_question_asked",
        metadata={"sufficient_context": True, "citation_count": 2},
    )
    event = store.list_events()[0]
    assert "api_key" not in event.metadata
    assert "answer" not in event.metadata
    assert "prompt" not in event.metadata


def test_record_from_context_writes_via_the_context_store(tmp_path):
    store = _store(tmp_path)
    context = AuditContext(store=store, actor="alice", role="viewer", request_id="req-1")

    record_from_context(context, action="workflow_started", resource_type="workflow", resource_id="architecture_review")

    events = store.list_events()
    assert len(events) == 1
    assert events[0].actor == "alice"
    assert events[0].request_id == "req-1"
    assert events[0].resource_id == "architecture_review"


def test_record_from_context_is_a_no_op_when_context_is_none(tmp_path):
    # Should not raise -- lets service functions accept an optional audit
    # context without an `if context:` guard at every call site.
    record_from_context(None, action="grounded_question_asked")


def test_verify_chain_is_valid_on_a_freshly_recorded_log(tmp_path):
    store = _store(tmp_path)
    for i in range(4):
        record_event(store, actor=f"user{i}", role="viewer", action="grounded_question_asked")

    result = store.verify_chain()

    assert result.valid is True
    assert result.total_events == 4
    assert result.first_invalid_sequence is None


def test_verify_chain_is_valid_on_an_empty_log(tmp_path):
    store = _store(tmp_path)
    result = store.verify_chain()
    assert result.valid is True
    assert result.total_events == 0


def test_verify_chain_detects_a_tampered_field(tmp_path):
    store = _store(tmp_path)
    record_event(store, actor="alice", role="viewer", action="grounded_question_asked")
    record_event(store, actor="bob", role="administrator", action="ingestion_run")

    with store._session_factory() as session:  # noqa: SLF001 -- direct DB tampering to simulate an attack
        from app.db.models import AuditEventRecord

        row = session.query(AuditEventRecord).filter_by(sequence_number=1).one()
        row.actor = "mallory"
        session.commit()

    result = store.verify_chain()

    assert result.valid is False
    assert result.first_invalid_sequence == 1
    assert "sequence 1" in result.reason


def test_store_round_trips_organization_id(tmp_path):
    store = _store(tmp_path)
    store.record(
        AuditEvent(actor="alice", role="viewer", action="grounded_question_asked", organization_id="org-1")
    )
    store.record(AuditEvent(actor="bob", role="viewer", action="grounded_question_asked"))

    events = store.list_events()
    assert events[0].organization_id is None
    assert events[1].organization_id == "org-1"


def test_verify_chain_detects_a_tampered_organization_id(tmp_path):
    store = _store(tmp_path)
    store.record(
        AuditEvent(actor="alice", role="viewer", action="grounded_question_asked", organization_id="org-1")
    )

    with store._session_factory() as session:  # noqa: SLF001 -- direct DB tampering to simulate an attack
        from app.db.models import AuditEventRecord

        row = session.query(AuditEventRecord).filter_by(sequence_number=1).one()
        row.organization_id = "org-2"
        session.commit()

    result = store.verify_chain()

    assert result.valid is False
    assert result.first_invalid_sequence == 1


def test_verify_chain_detects_a_broken_previous_hash_link(tmp_path):
    store = _store(tmp_path)
    record_event(store, actor="alice", role="viewer", action="grounded_question_asked")
    record_event(store, actor="bob", role="administrator", action="ingestion_run")

    with store._session_factory() as session:  # noqa: SLF001
        from app.db.models import AuditEventRecord

        row = session.query(AuditEventRecord).filter_by(sequence_number=2).one()
        row.previous_hash = "0" * 64
        session.commit()

    result = store.verify_chain()

    assert result.valid is False
    assert result.first_invalid_sequence == 2
