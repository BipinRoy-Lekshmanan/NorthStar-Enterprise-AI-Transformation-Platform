"""Tests for `app.audit` -- the audit event model, append-only JSONL
store, and the `record_event`/`record_from_context` helpers (Milestone 7).
"""

from app.audit.logger import AuditContext, record_event, record_from_context
from app.audit.models import AuditEvent
from app.audit.store import AuditStore


def test_audit_event_defaults():
    event = AuditEvent(actor="alice", role="viewer", action="grounded_question_asked")
    assert event.outcome == "success"
    assert event.metadata == {}
    assert event.resource_type is None
    assert event.timestamp is not None


def test_store_records_and_lists_events(tmp_path):
    store = AuditStore(tmp_path / "audit_log")
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
    store = AuditStore(tmp_path / "audit_log")
    for i in range(5):
        record_event(store, actor=f"user{i}", role="viewer", action="grounded_question_asked")

    events = store.list_events(limit=2)
    assert len(events) == 2
    assert events[0].actor == "user4"
    assert events[1].actor == "user3"


def test_store_returns_empty_list_when_no_events_recorded(tmp_path):
    store = AuditStore(tmp_path / "audit_log")
    assert store.list_events() == []


def test_store_creates_its_directory_if_missing(tmp_path):
    target = tmp_path / "nested" / "audit_log"
    assert not target.exists()
    AuditStore(target)
    assert target.exists()


def test_metadata_never_contains_secrets_by_construction(tmp_path):
    # This is a design-level check: record_event's signature only accepts a
    # plain metadata dict the caller controls -- there is no path for a full
    # prompt, answer, or API key to be captured automatically.
    store = AuditStore(tmp_path / "audit_log")
    record_event(
        store, actor="alice", role="viewer", action="grounded_question_asked",
        metadata={"sufficient_context": True, "citation_count": 2},
    )
    event = store.list_events()[0]
    assert "api_key" not in event.metadata
    assert "answer" not in event.metadata
    assert "prompt" not in event.metadata


def test_record_from_context_writes_via_the_context_store(tmp_path):
    store = AuditStore(tmp_path / "audit_log")
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
