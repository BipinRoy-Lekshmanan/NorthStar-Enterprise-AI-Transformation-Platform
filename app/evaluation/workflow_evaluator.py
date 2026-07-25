"""Milestone 6 workflow evaluation runner.

Checks the full workflow engine against a small seed dataset
(`data/evaluation_sets/milestone6_workflow_eval.json`): whether the
workflow reached the expected terminal status, ran the expected stages,
surfaced the expected findings/evidence gaps, paused for approval when
expected, produced the expected bounded recommendation (where
applicable), and carried citations through to the final report.
Deterministic checks only -- no LLM-as-judge, same philosophy as
`app.evaluation.rag_evaluator`.

A new sibling file rather than an extension of `rag_evaluator.py`:
workflow eval cases have a different shape (multi-stage expectations,
new metric dimensions) that would force nullable fields and branching
into an already-complete, tested module for no reuse benefit.

Known scope limitation: conflict-detection eval cases are intentionally
absent from the default dataset. `app.workflows.conflict_detection`
matches literal marker phrases in advisor *answer text*, but the
offline, no-API-key `FakeModelProvider` used by this evaluator (per the
milestone's "must not call external APIs" requirement) always returns
the same content-free placeholder text -- it never contains those
phrases, so a conflict can never actually fire here. Conflict detection
is exercised directly with literal strings in
`tests/test_workflow_conflict_detection.py` instead. The same applies to
`NO_GO`/`GO_WITH_CONDITIONS` recommendations for Production Readiness
Review, which require a conflict-detected finding to reach -- only `GO`
and `INSUFFICIENT_EVIDENCE` (driven by evidence gaps, not advisor prose)
are exercised in the default dataset; the other two are covered by
`tests/test_workflow_engine.py` using a `FakeModelProvider` with a
`canned_answer` containing the relevant marker phrases.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.config.settings import PROJECT_ROOT
from app.models.workflow import ApprovalDecision, WorkflowExecution
from app.workflows.engine import WorkflowEngine, build_default_workflow_engine
from app.workflows.synthesis import dedupe_citations

logger = logging.getLogger(__name__)

DEFAULT_DATASET_PATH = PROJECT_ROOT / "data" / "evaluation_sets" / "milestone6_workflow_eval.json"


@dataclass(frozen=True)
class WorkflowEvalCase:
    id: str
    workflow_id: str
    input_file: str
    expected_stages: list[str] = field(default_factory=list)
    expected_findings: list[str] = field(default_factory=list)
    expected_final_recommendation: str | None = None
    requires_citations: bool = False
    requires_human_approval: bool = False
    expect_conflict: bool = False
    approval_decision: str = "approve"


@dataclass(frozen=True)
class WorkflowEvalCaseResult:
    case_id: str
    passed: bool
    checks: dict[str, bool]
    notes: list[str]
    final_status: str
    advisor_insufficient_count: int = 0
    advisor_total_count: int = 0


def load_eval_cases(path: Path = DEFAULT_DATASET_PATH) -> list[WorkflowEvalCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        WorkflowEvalCase(
            id=item["id"],
            workflow_id=item["workflow_id"],
            input_file=item["input_file"],
            expected_stages=item.get("expected_stages", []),
            expected_findings=item.get("expected_findings", []),
            expected_final_recommendation=item.get("expected_final_recommendation"),
            requires_citations=item.get("requires_citations", False),
            requires_human_approval=item.get("requires_human_approval", False),
            expect_conflict=item.get("expect_conflict", False),
            approval_decision=item.get("approval_decision", "approve"),
        )
        for item in raw
    ]


def _load_input(input_file: str) -> dict:
    path = PROJECT_ROOT / input_file
    return json.loads(path.read_text(encoding="utf-8"))


def _findings_text(execution: WorkflowExecution) -> str:
    parts = []
    for result in execution.stage_results:
        for item in result.structured_output.get("findings", []):
            parts.append(f"{item.get('title', '')} {item.get('description', '')}")
        for item in result.structured_output.get("evidence_gaps", []):
            parts.append(f"{item.get('field', '')} {item.get('description', '')}")
    return " | ".join(parts).lower()


def _has_conflict(execution: WorkflowExecution) -> bool:
    return any(
        item.get("category") == "conflict"
        for result in execution.stage_results
        for item in result.structured_output.get("findings", [])
    )


def _final_recommendation(execution: WorkflowExecution) -> str | None:
    for result in reversed(execution.stage_results):
        sections = result.structured_output.get("report_sections")
        if sections:
            return sections.get("Recommendation")
    return None


def _advisor_insufficient_count(execution: WorkflowExecution) -> tuple[int, int]:
    advisor_results = [result for result in execution.stage_results if result.advisor_name]
    insufficient = sum(1 for result in advisor_results if result.diagnostics.get("sufficient_context") is False)
    return insufficient, len(advisor_results)


def evaluate_case(engine: WorkflowEngine, case: WorkflowEvalCase) -> WorkflowEvalCaseResult:
    checks: dict[str, bool] = {}
    notes: list[str] = []

    raw_input = _load_input(case.input_file)
    execution = engine.run(case.workflow_id, raw_input)

    paused = execution.status == "awaiting_approval"
    checks["approval_checkpoint_matches"] = paused == case.requires_human_approval
    if not checks["approval_checkpoint_matches"]:
        notes.append(f"expected requires_human_approval={case.requires_human_approval}, got paused={paused}")

    if paused:
        execution = engine.approve(
            execution.execution_id, ApprovalDecision(decision=case.approval_decision, reviewer="evaluator")
        )

    checks["completed"] = execution.status == "completed"
    if not checks["completed"]:
        notes.append(f"expected status=completed, got '{execution.status}'")

    executed_stage_ids = {result.stage_id for result in execution.stage_results}
    missing_stages = [stage_id for stage_id in case.expected_stages if stage_id not in executed_stage_ids]
    checks["expected_stages_executed"] = not missing_stages
    if missing_stages:
        notes.append(f"expected stages not executed: {missing_stages}")

    findings_text = _findings_text(execution)
    missing_findings = [text for text in case.expected_findings if text.lower() not in findings_text]
    checks["expected_findings_present"] = not missing_findings
    if missing_findings:
        notes.append(f"expected findings not present: {missing_findings}")

    if case.expected_final_recommendation is not None:
        actual = _final_recommendation(execution)
        checks["final_recommendation_matches"] = actual == case.expected_final_recommendation
        if not checks["final_recommendation_matches"]:
            notes.append(f"expected recommendation={case.expected_final_recommendation}, got {actual!r}")
    else:
        checks["final_recommendation_matches"] = True

    if case.requires_citations:
        checks["has_citations"] = len(dedupe_citations(execution.stage_results)) > 0
        if not checks["has_citations"]:
            notes.append("expected at least one citation, got none")
    else:
        checks["has_citations"] = True

    if case.expect_conflict:
        checks["conflict_detected"] = _has_conflict(execution)
        if not checks["conflict_detected"]:
            notes.append("expected a detected conflict, found none")
    else:
        checks["conflict_detected"] = True

    insufficient_count, advisor_total = _advisor_insufficient_count(execution)

    return WorkflowEvalCaseResult(
        case_id=case.id,
        passed=all(checks.values()),
        checks=checks,
        notes=notes,
        final_status=execution.status,
        advisor_insufficient_count=insufficient_count,
        advisor_total_count=advisor_total,
    )


def run_evaluation(engine: WorkflowEngine, cases: list[WorkflowEvalCase]) -> list[WorkflowEvalCaseResult]:
    """Milestone 8: isolates each case -- one case raising (a provider
    outage, a missing input fixture, an unexpected error) is recorded
    as a failed result rather than crashing the whole batch and losing
    every already-computed result alongside it."""
    results = []
    for case in cases:
        try:
            results.append(evaluate_case(engine, case))
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: any case-level failure must not lose the rest of the batch
            logger.warning("Workflow evaluation case '%s' raised an exception: %s", case.id, exc)
            results.append(
                WorkflowEvalCaseResult(
                    case_id=case.id, passed=False, checks={}, notes=[f"Case raised an exception: {exc}"],
                    final_status="error",
                )
            )
    return results


def _rate(results: list[WorkflowEvalCaseResult], check_name: str) -> float:
    total = len(results) or 1
    return sum(1 for result in results if result.checks.get(check_name)) / total


def print_report(results: list[WorkflowEvalCaseResult]) -> None:
    passed = sum(1 for result in results if result.passed)
    print(f"\nMilestone 6 workflow evaluation: {passed}/{len(results)} case(s) passed\n")
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.case_id} (final_status={result.final_status})")
        for note in result.notes:
            print(f"    - {note}")
    print()

    total_insufficient = sum(result.advisor_insufficient_count for result in results)
    total_advisor_calls = sum(result.advisor_total_count for result in results)
    fallback_rate = (total_insufficient / total_advisor_calls) if total_advisor_calls else 0.0

    print("Aggregate metrics:")
    print(f"  workflow_completion_rate:      {_rate(results, 'completed'):.0%}")
    print(f"  expected_stage_execution_rate: {_rate(results, 'expected_stages_executed'):.0%}")
    print(f"  finding_detection_rate:        {_rate(results, 'expected_findings_present'):.0%}")
    print(f"  approval_checkpoint_accuracy:  {_rate(results, 'approval_checkpoint_matches'):.0%}")
    print(f"  final_recommendation_accuracy: {_rate(results, 'final_recommendation_matches'):.0%}")
    print(f"  citation_presence_rate:        {_rate(results, 'has_citations'):.0%}")
    print(f"  conflict_detection_rate:       {_rate(results, 'conflict_detected'):.0%}")
    print(f"  advisor_insufficient_context_rate (fallback): {fallback_rate:.0%}")
    print()


def main() -> None:
    import argparse

    from app.config.logging import configure_logging

    parser = argparse.ArgumentParser(description="Run the Milestone 6 workflow evaluation dataset.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH, help="Path to the eval JSON file")
    args = parser.parse_args()

    configure_logging()
    cases = load_eval_cases(args.dataset)
    engine = build_default_workflow_engine()
    results = run_evaluation(engine, cases)
    print_report(results)


if __name__ == "__main__":
    main()
