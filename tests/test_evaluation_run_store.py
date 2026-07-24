"""Tests for `app.evaluation.run_models.EvaluationRun` and
`app.evaluation.run_store.EvaluationRunStore` (Milestone 7) -- mirrors
`tests/test_workflow_store.py`'s coverage of `WorkflowStore`.
"""

import pytest

from app.evaluation.run_models import EvaluationRun
from app.evaluation.run_store import EvaluationRunStore, EvaluationRunStoreError


def _run(**overrides):
    defaults = dict(run_id="run-1", category="rag", total_cases=4, passed_cases=3)
    defaults.update(overrides)
    return EvaluationRun(**defaults)


def test_pass_rate_computed_from_counts():
    run = _run(total_cases=4, passed_cases=3)
    assert run.pass_rate == 0.75


def test_pass_rate_is_zero_when_no_cases():
    run = _run(total_cases=0, passed_cases=0)
    assert run.pass_rate == 0.0


def test_invalid_category_is_rejected():
    with pytest.raises(ValueError):
        _run(category="bogus")


def test_invalid_status_is_rejected():
    with pytest.raises(ValueError):
        _run(status="bogus")


def test_store_save_then_load_round_trips(tmp_path):
    store = EvaluationRunStore(tmp_path / "evaluation_runs")
    run = _run(results=[{"case_id": "c1", "passed": True}], summary={"pass_rate": 0.75})
    store.save(run)

    loaded = store.load("run-1")
    assert loaded.run_id == "run-1"
    assert loaded.results == [{"case_id": "c1", "passed": True}]
    assert loaded.summary == {"pass_rate": 0.75}


def test_store_load_unknown_run_raises(tmp_path):
    store = EvaluationRunStore(tmp_path / "evaluation_runs")
    with pytest.raises(EvaluationRunStoreError):
        store.load("does-not-exist")


def test_store_list_run_ids_is_sorted(tmp_path):
    store = EvaluationRunStore(tmp_path / "evaluation_runs")
    store.save(_run(run_id="run-b"))
    store.save(_run(run_id="run-a"))
    assert store.list_run_ids() == ["run-a", "run-b"]


def test_store_creates_directory_if_missing(tmp_path):
    directory = tmp_path / "nested" / "evaluation_runs"
    assert not directory.exists()
    EvaluationRunStore(directory)
    assert directory.exists()
