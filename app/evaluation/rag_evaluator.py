"""Milestone 3 evaluation runner.

Checks the full RAG workflow against a small seed dataset
(`data/evaluation_sets/milestone3_eval.json`): whether expected documents
were retrievable, whether citations were produced when expected, whether
sufficient-context classification matches expectations, and whether
required concepts appear in the answer text (best-effort substring
match). Deterministic checks only -- no LLM-as-judge.

`main()` also accepts `--category workflows`, which defers entirely to
`app.evaluation.workflow_evaluator` (the Milestone 6 evaluation runner)
so `python -m app.rag.evaluate --category workflows` and
`python -m app.evaluation.workflow_evaluator` run the identical thing --
one CLI entry point for both evaluation datasets, same reasoning
`app.rag.index`/`app.rag.ask`/`app.rag.evaluate` already share one
namespace instead of proliferating commands.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from app.config.settings import PROJECT_ROOT
from app.models.query import RetrievalQuery
from app.rag.pipeline import RagService, build_default_rag_service

logger = logging.getLogger(__name__)

DEFAULT_DATASET_PATH = PROJECT_ROOT / "data" / "evaluation_sets" / "milestone3_eval.json"
DEFAULT_EVAL_TOP_K = 10


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    expected_documents: list[str]
    must_include_concepts: list[str]
    requires_citation: bool
    expected_sufficient_context: bool


@dataclass(frozen=True)
class EvalCaseResult:
    case_id: str
    passed: bool
    checks: dict[str, bool]
    notes: list[str]


def load_eval_cases(path: Path = DEFAULT_DATASET_PATH) -> list[EvalCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        EvalCase(
            id=item["id"],
            question=item["question"],
            expected_documents=item.get("expected_documents", []),
            must_include_concepts=item.get("must_include_concepts", []),
            requires_citation=item.get("requires_citation", False),
            expected_sufficient_context=item.get("expected_sufficient_context", True),
        )
        for item in raw
    ]


def evaluate_case(service: RagService, case: EvalCase, top_k: int = DEFAULT_EVAL_TOP_K) -> EvalCaseResult:
    answer = service.ask(case.question, top_k=top_k)
    checks: dict[str, bool] = {}
    notes: list[str] = []

    checks["sufficient_context_matches"] = answer.sufficient_context == case.expected_sufficient_context
    if not checks["sufficient_context_matches"]:
        notes.append(
            f"expected sufficient_context={case.expected_sufficient_context}, got {answer.sufficient_context}"
        )

    if case.expected_documents:
        # Check raw retrieval directly (not just citations) -- a fairer
        # signal for retrieval quality, independent of citation behavior.
        retrieval_response = service.retriever.retrieve(RetrievalQuery(text=case.question, top_k=top_k))
        retrieved_files = {r.chunk.source_file for r in retrieval_response.results}
        found = set(case.expected_documents) & retrieved_files
        checks["expected_documents_retrieved"] = bool(found)
        if not checks["expected_documents_retrieved"]:
            notes.append(f"expected one of {case.expected_documents}, retrieved {sorted(retrieved_files)}")
    else:
        checks["expected_documents_retrieved"] = True

    if case.requires_citation:
        checks["has_citations"] = len(answer.citations) > 0
        if not checks["has_citations"]:
            notes.append("expected at least one citation, got none")
    else:
        checks["has_citations"] = True

    if case.must_include_concepts:
        answer_lower = answer.answer.lower()
        missing = [c for c in case.must_include_concepts if c.lower() not in answer_lower]
        checks["concepts_present"] = not missing
        if missing:
            notes.append(f"missing concepts: {missing}")
    else:
        checks["concepts_present"] = True

    return EvalCaseResult(case_id=case.id, passed=all(checks.values()), checks=checks, notes=notes)


def run_evaluation(service: RagService, cases: list[EvalCase], top_k: int = DEFAULT_EVAL_TOP_K) -> list[EvalCaseResult]:
    return [evaluate_case(service, case, top_k=top_k) for case in cases]


def _print_report(results: list[EvalCaseResult]) -> None:
    passed = sum(1 for r in results if r.passed)
    print(f"\nMilestone 3 evaluation: {passed}/{len(results)} case(s) passed\n")
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.case_id}")
        for note in result.notes:
            print(f"    - {note}")
    print()


def main() -> None:
    import argparse

    from app.config.logging import configure_logging

    parser = argparse.ArgumentParser(description="Run a Northstar evaluation dataset.")
    parser.add_argument(
        "--category", choices=["rag", "workflows"], default="rag",
        help="Which evaluation dataset to run: 'rag' (Milestone 3 grounded-RAG seed set, default) "
             "or 'workflows' (Milestone 6 workflow seed set)",
    )
    parser.add_argument("--dataset", type=Path, default=None, help="Path to the eval JSON file (defaults per --category)")
    args = parser.parse_args()

    configure_logging()

    if args.category == "workflows":
        # Deferred import: rag_evaluator has no module-level dependency on
        # app.workflows, only when --category workflows is actually chosen.
        from app.evaluation.workflow_evaluator import (
            DEFAULT_DATASET_PATH as WORKFLOW_DATASET_PATH,
            load_eval_cases as load_workflow_eval_cases,
            print_report as print_workflow_report,
            run_evaluation as run_workflow_evaluation,
        )
        from app.workflows.engine import build_default_workflow_engine

        cases = load_workflow_eval_cases(args.dataset or WORKFLOW_DATASET_PATH)
        engine = build_default_workflow_engine()
        results = run_workflow_evaluation(engine, cases)
        print_workflow_report(results)
        return

    cases = load_eval_cases(args.dataset or DEFAULT_DATASET_PATH)
    service = build_default_rag_service()
    results = run_evaluation(service, cases)
    _print_report(results)


if __name__ == "__main__":
    main()
