"""Tests for `app.operations.background.OperationRunner` (Milestone 8)."""

import threading
import time

import pytest

from app.db.engine import build_engine, build_session_factory, create_all
from app.operations.background import OperationRunner, UnknownOperationError


def _runner(tmp_path) -> OperationRunner:
    engine = build_engine(f"sqlite:///{(tmp_path / 'ops.db').as_posix()}")
    create_all(engine)
    return OperationRunner(build_session_factory(engine))


def _wait_until_terminal(runner, operation_id, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        summary = runner.get_operation(operation_id)
        if summary.status in ("completed", "failed"):
            return summary
        time.sleep(0.01)
    raise TimeoutError(f"Operation {operation_id} did not reach a terminal status in time.")


def test_start_runs_the_function_in_the_background_and_records_success(tmp_path):
    runner = _runner(tmp_path)

    operation_id = runner.start("test_op", lambda: {"answer": 42}, created_by="alice")
    summary = _wait_until_terminal(runner, operation_id)

    assert summary.status == "completed"
    assert summary.result == {"answer": 42}
    assert summary.error_message is None
    assert summary.created_by == "alice"
    assert summary.started_at is not None
    assert summary.completed_at is not None


def test_start_records_a_failure_without_raising_on_the_caller(tmp_path):
    runner = _runner(tmp_path)

    def _boom():
        raise ValueError("simulated failure")

    operation_id = runner.start("test_op", _boom)
    summary = _wait_until_terminal(runner, operation_id)

    assert summary.status == "failed"
    assert summary.result is None
    assert "simulated failure" in summary.error_message


def test_get_operation_starts_as_pending_or_running_before_completion(tmp_path):
    runner = _runner(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def _slow():
        started.set()
        release.wait(timeout=2.0)
        return {"done": True}

    operation_id = runner.start("test_op", _slow)
    started.wait(timeout=2.0)

    summary = runner.get_operation(operation_id)
    assert summary.status in ("pending", "running")

    release.set()
    final = _wait_until_terminal(runner, operation_id)
    assert final.status == "completed"


def test_get_unknown_operation_raises(tmp_path):
    runner = _runner(tmp_path)
    with pytest.raises(UnknownOperationError):
        runner.get_operation("does-not-exist")


def test_list_operations_filters_by_type_and_status(tmp_path):
    runner = _runner(tmp_path)
    op1 = runner.start("rebuild", lambda: {"n": 1})
    op2 = runner.start("ingest", lambda: {"n": 2})
    _wait_until_terminal(runner, op1)
    _wait_until_terminal(runner, op2)

    rebuilds = runner.list_operations(operation_type="rebuild")
    assert [o.operation_id for o in rebuilds] == [op1]

    completed = runner.list_operations(status="completed")
    assert {o.operation_id for o in completed} == {op1, op2}


def test_list_operations_orders_most_recent_first(tmp_path):
    runner = _runner(tmp_path)
    op1 = runner.start("test_op", lambda: {})
    _wait_until_terminal(runner, op1)
    op2 = runner.start("test_op", lambda: {})
    _wait_until_terminal(runner, op2)

    listed = runner.list_operations()
    assert listed[0].operation_id == op2
    assert listed[1].operation_id == op1
