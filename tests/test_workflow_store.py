"""Tests for `app.workflows.store.WorkflowStore` -- JSON persistence with
save/reload round-tripping, including partial (mid-execution) state.
"""

from datetime import datetime, timezone

import pytest

from app.models.workflow import WorkflowExecution, WorkflowStageResult
from app.workflows.store import WorkflowStore, WorkflowStoreError

_NOW = datetime.now(timezone.utc)


def test_save_then_load_round_trips_execution(tmp_path):
    store = WorkflowStore(tmp_path / "workflow_store")
    execution = WorkflowExecution(execution_id="e1", workflow_id="w1", workflow_version="1.0.0", status="running")

    store.save(execution)
    loaded = store.load("e1")

    assert loaded.execution_id == "e1"
    assert loaded.workflow_id == "w1"
    assert loaded.status == "running"


def test_exists_reflects_saved_state(tmp_path):
    store = WorkflowStore(tmp_path / "workflow_store")
    assert store.exists("e1") is False

    store.save(WorkflowExecution(execution_id="e1", workflow_id="w1", workflow_version="1.0.0", status="running"))
    assert store.exists("e1") is True


def test_load_missing_execution_raises(tmp_path):
    store = WorkflowStore(tmp_path / "workflow_store")
    with pytest.raises(WorkflowStoreError, match="No workflow execution found"):
        store.load("does-not-exist")


def test_partial_stage_results_are_preserved_across_save_and_load(tmp_path):
    store = WorkflowStore(tmp_path / "workflow_store")
    partial_stage = WorkflowStageResult(
        stage_id="validate", stage_name="Validate", status="completed", started_at=_NOW, completed_at=_NOW,
        structured_output={"evidence_gaps": [{"field": "x", "description": "d", "severity": "high", "blocking": False}]},
    )
    execution = WorkflowExecution(
        execution_id="e2", workflow_id="w1", workflow_version="1.0.0", status="awaiting_approval",
        current_stage="approval", stage_results=[partial_stage],
    )

    store.save(execution)
    loaded = store.load("e2")

    assert loaded.status == "awaiting_approval"
    assert loaded.current_stage == "approval"
    assert len(loaded.stage_results) == 1
    assert loaded.stage_results[0].structured_output["evidence_gaps"][0]["field"] == "x"


def test_save_overwrites_previous_state_for_same_execution_id(tmp_path):
    store = WorkflowStore(tmp_path / "workflow_store")
    store.save(WorkflowExecution(execution_id="e1", workflow_id="w1", workflow_version="1.0.0", status="running"))
    store.save(WorkflowExecution(execution_id="e1", workflow_id="w1", workflow_version="1.0.0", status="completed"))

    loaded = store.load("e1")
    assert loaded.status == "completed"


def test_list_execution_ids_returns_all_saved_executions(tmp_path):
    store = WorkflowStore(tmp_path / "workflow_store")
    store.save(WorkflowExecution(execution_id="e1", workflow_id="w1", workflow_version="1.0.0", status="running"))
    store.save(WorkflowExecution(execution_id="e2", workflow_id="w1", workflow_version="1.0.0", status="completed"))

    assert store.list_execution_ids() == ["e1", "e2"]


def test_corrupt_execution_file_raises_a_clear_error(tmp_path):
    directory = tmp_path / "workflow_store"
    directory.mkdir()
    (directory / "bad.json").write_text("{not valid json", encoding="utf-8")

    store = WorkflowStore(directory)
    with pytest.raises(WorkflowStoreError, match="corrupt"):
        store.load("bad")


def test_store_creates_its_directory_if_missing(tmp_path):
    target = tmp_path / "nested" / "workflow_store"
    assert not target.exists()
    WorkflowStore(target)
    assert target.exists()
