"""Application-service facade over Milestones 3 and 6's evaluation runners.

Neither `app.evaluation.rag_evaluator` nor `app.evaluation.workflow_evaluator`
is modified -- this module calls exactly one of their `load_eval_cases`/
`run_evaluation` pairs, wraps the result list in an `EvaluationRun`, and
persists it via `EvaluationRunStore`. Per-check pass rates are computed
generically from whatever keys appear in each result's `checks` dict
rather than hard-coding either evaluator's specific check names, so this
module needs no changes if a future evaluator adds a new check.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.audit.logger import AuditContext, record_from_context
from app.evaluation.run_models import EvaluationRun
from app.evaluation.run_store import EvaluationRunStore
from app.rag.pipeline import RagService
from app.telemetry.metrics import evaluation_duration_seconds, evaluation_pass_rate, evaluation_runs_total
from app.telemetry.tracing import traced_span
from app.workflows.engine import WorkflowEngine


def _aggregate_check_rates(results: list[dict]) -> dict[str, float]:
    check_names: set[str] = set()
    for result in results:
        check_names.update(result.get("checks", {}))

    total = len(results) or 1
    return {
        name: sum(1 for result in results if result.get("checks", {}).get(name)) / total
        for name in sorted(check_names)
    }


def run_rag_evaluation(service: RagService, dataset_path: Path | None = None) -> EvaluationRun:
    from app.evaluation.rag_evaluator import DEFAULT_DATASET_PATH, load_eval_cases, run_evaluation

    cases = load_eval_cases(dataset_path or DEFAULT_DATASET_PATH)
    case_results = run_evaluation(service, cases)
    results = [
        {"case_id": r.case_id, "passed": r.passed, "checks": r.checks, "notes": r.notes} for r in case_results
    ]
    passed_cases = sum(1 for r in case_results if r.passed)

    return EvaluationRun(
        run_id=uuid.uuid4().hex, category="rag", completed_at=datetime.now(timezone.utc),
        total_cases=len(case_results), passed_cases=passed_cases, results=results,
        summary=_aggregate_check_rates(results),
    )


def run_workflow_evaluation(engine: WorkflowEngine, dataset_path: Path | None = None) -> EvaluationRun:
    from app.evaluation.workflow_evaluator import DEFAULT_DATASET_PATH, load_eval_cases, run_evaluation

    cases = load_eval_cases(dataset_path or DEFAULT_DATASET_PATH)
    case_results = run_evaluation(engine, cases)
    results = [
        {
            "case_id": r.case_id, "passed": r.passed, "checks": r.checks, "notes": r.notes,
            "final_status": r.final_status, "advisor_insufficient_count": r.advisor_insufficient_count,
            "advisor_total_count": r.advisor_total_count,
        }
        for r in case_results
    ]
    passed_cases = sum(1 for r in case_results if r.passed)

    return EvaluationRun(
        run_id=uuid.uuid4().hex, category="workflows", completed_at=datetime.now(timezone.utc),
        total_cases=len(case_results), passed_cases=passed_cases, results=results,
        summary=_aggregate_check_rates(results),
    )


def run_and_save_evaluation(
    store: EvaluationRunStore, category: str, *, service: RagService | None = None,
    engine: WorkflowEngine | None = None, audit: AuditContext | None = None,
) -> EvaluationRun:
    with traced_span("evaluation.run", category=category):
        if category == "workflows":
            run = run_workflow_evaluation(engine)
        else:
            run = run_rag_evaluation(service)
    store.save(run)

    evaluation_runs_total.labels(category=run.category).inc()
    evaluation_pass_rate.labels(category=run.category).set(run.pass_rate)
    if run.completed_at is not None:
        duration_seconds = (run.completed_at - run.started_at).total_seconds()
        evaluation_duration_seconds.labels(category=run.category).observe(duration_seconds)

    record_from_context(
        audit, action="evaluation_run_triggered", resource_type="evaluation_run", resource_id=run.run_id,
        metadata={"category": run.category, "total_cases": run.total_cases, "passed_cases": run.passed_cases},
    )
    return run


def list_runs(store: EvaluationRunStore, category: str | None = None) -> list[EvaluationRun]:
    runs = [store.load(run_id) for run_id in store.list_run_ids()]
    if category:
        runs = [run for run in runs if run.category == category]
    return sorted(runs, key=lambda run: run.started_at, reverse=True)


def get_run(store: EvaluationRunStore, run_id: str) -> EvaluationRun:
    return store.load(run_id)
