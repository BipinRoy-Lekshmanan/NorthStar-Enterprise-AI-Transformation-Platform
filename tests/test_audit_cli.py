"""Tests for `python -m app.audit verify` (Milestone 8)."""

from app.audit import cli as audit_cli
from app.audit.models import AuditEvent
from app.audit.store import AuditStore


def _sqlite_url(tmp_path, name="audit.db"):
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def test_verify_returns_0_on_an_intact_chain(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _sqlite_url(tmp_path))
    store = AuditStore.from_env()
    store.record(AuditEvent(actor="alice", role="viewer", action="grounded_question_asked"))
    store.record(AuditEvent(actor="bob", role="administrator", action="ingestion_run"))

    assert audit_cli.main(["verify"]) == 0


def test_verify_returns_0_on_an_empty_log(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _sqlite_url(tmp_path))
    assert audit_cli.main(["verify"]) == 0


def test_verify_returns_1_on_a_tampered_chain(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", _sqlite_url(tmp_path))
    store = AuditStore.from_env()
    store.record(AuditEvent(actor="alice", role="viewer", action="grounded_question_asked"))

    with store._session_factory() as session:  # noqa: SLF001 -- direct DB tampering to simulate an attack
        from app.db.models import AuditEventRecord

        row = session.query(AuditEventRecord).filter_by(sequence_number=1).one()
        row.action = "tampered_action"
        session.commit()

    exit_code = audit_cli.main(["verify"])

    assert exit_code == 1
    assert "CORRUPTED" in capsys.readouterr().out
