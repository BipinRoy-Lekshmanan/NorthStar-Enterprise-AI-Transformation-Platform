"""Deterministic workflow execution engine (Milestone 6).

Walks a `WorkflowDefinition.execution_order` (precomputed once at
registry-load time -- see `app.workflows.definitions`), dispatching each
stage by its closed `stage_type` to the corresponding stage-body module
(`app.workflows.input_validation`, `app.agents.registry` for advisor
calls, `app.workflows.conflict_detection`, `app.workflows.synthesis`,
`app.workflows.report`) and persisting the execution after every single
stage via `app.workflows.store.WorkflowStore` -- that persistence is
what makes an execution safely resumable from any point, including a
process crash mid-run.

No stage ever creates another stage, no parallelism, no dynamic
scheduling: this is a fixed sequential walk over config that was
validated once at import time. `human_approval` stages are the only
branch point, and even that "branch" is binary (pause or don't) and
config-driven (`approval_condition`), never model-decided.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.agents.registry import get_advisor
from app.config.settings import RagSettings, RetrievalSettings, WorkflowSettings
from app.models.workflow import (
    ApprovalDecision,
    EvidenceGap,
    ReviewFinding,
    WorkflowExecution,
    WorkflowStageResult,
)
from app.rag.pipeline import QuestionValidationError, RagService, build_default_rag_service
from app.services.llm_service import ModelProviderError
from app.workflows.conflict_detection import detect_conflicts
from app.workflows.definitions import WorkflowDefinition, WorkflowStageDefinition
from app.workflows.input_validation import validate_input
from app.workflows.registry import get_workflow
from app.workflows.report import build_final_report
from app.workflows.store import WorkflowStore
from app.workflows.synthesis import dedupe_citations, run_synthesis_stage

_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "changes_requested"}


class WorkflowEngineError(Exception):
    """Raised for invalid engine operations (unknown/terminal execution, disabled workflow, ...)."""


class _SafeDict(dict):
    """Renders a missing question_template field as "(not provided)"
    instead of raising -- most workflow input fields are optional."""

    def __missing__(self, key: str) -> str:
        return "(not provided)"


class WorkflowEngine:
    def __init__(self, service: RagService, store: WorkflowStore, rag_settings: RagSettings | None = None):
        self._service = service
        self._store = store
        self._rag_settings = rag_settings or RagSettings.from_env()

    @property
    def store(self) -> WorkflowStore:
        """Exposes the underlying `WorkflowStore` for tooling (e.g. the CLI's
        `status` command) that needs a read-only execution lookup without
        running or mutating anything."""
        return self._store

    # -- public API ---------------------------------------------------------------------

    def run(self, workflow_id: str, inputs: dict) -> WorkflowExecution:
        definition = get_workflow(workflow_id)
        if not definition.enabled:
            raise WorkflowEngineError(f"Workflow '{workflow_id}' is disabled.")

        execution = WorkflowExecution(
            execution_id=uuid.uuid4().hex,
            workflow_id=definition.workflow_id,
            workflow_version=definition.version,
            status="running",
            inputs=inputs,
        )
        self._store.save(execution)
        return self._advance(definition, execution)

    def resume(self, execution_id: str) -> WorkflowExecution:
        execution = self._store.load(execution_id)
        if execution.status in _TERMINAL_STATUSES:
            raise WorkflowEngineError(
                f"Execution '{execution_id}' has terminal status '{execution.status}' and cannot be resumed."
            )
        if execution.status == "awaiting_approval":
            raise WorkflowEngineError(
                f"Execution '{execution_id}' is awaiting approval; call approve() before resume()."
            )
        definition = get_workflow(execution.workflow_id)
        return self._advance(definition, execution)

    def approve(self, execution_id: str, decision: ApprovalDecision) -> WorkflowExecution:
        execution = self._store.load(execution_id)
        if execution.status != "awaiting_approval":
            raise WorkflowEngineError(
                f"Execution '{execution_id}' is not awaiting approval (status='{execution.status}')."
            )
        definition = get_workflow(execution.workflow_id)
        execution = self._record_approval(execution, execution.current_stage, decision)

        if decision.decision == "approve":
            execution = execution.model_copy(update={"status": "running"})
            self._store.save(execution)
            return self._advance(definition, execution)

        new_status = "changes_requested" if decision.decision == "request_changes" else "cancelled"
        execution = execution.model_copy(update={"status": new_status, "completed_at": datetime.now(timezone.utc)})
        self._store.save(execution)
        return execution

    def cancel(self, execution_id: str) -> WorkflowExecution:
        execution = self._store.load(execution_id)
        if execution.status in _TERMINAL_STATUSES:
            raise WorkflowEngineError(f"Execution '{execution_id}' already has terminal status '{execution.status}'.")
        execution = execution.model_copy(update={"status": "cancelled", "completed_at": datetime.now(timezone.utc)})
        self._store.save(execution)
        return execution

    # -- internal: main loop --------------------------------------------------------------

    def _advance(self, definition: WorkflowDefinition, execution: WorkflowExecution) -> WorkflowExecution:
        completed_ids = {r.stage_id for r in execution.stage_results if r.status in ("completed", "skipped")}

        for stage_id in definition.execution_order:
            if stage_id in completed_ids:
                continue
            stage = _stage_by_id(definition, stage_id)

            if stage.skip_unless_input_truthy and not self._is_truthy(
                execution.inputs.get(stage.skip_unless_input_truthy)
            ):
                skipped = WorkflowStageResult(
                    stage_id=stage.stage_id, stage_name=stage.name, status="skipped",
                    started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
                )
                execution = execution.model_copy(update={
                    "stage_results": execution.stage_results + [skipped],
                    "current_stage": stage.stage_id,
                })
                completed_ids.add(stage.stage_id)
                self._store.save(execution)
                continue

            if stage.stage_type == "human_approval":
                execution = self._run_human_approval(stage, execution)
                if execution.status == "awaiting_approval":
                    self._store.save(execution)
                    return execution
                completed_ids.add(stage.stage_id)
                self._store.save(execution)
                continue

            result = self._run_stage_body(definition, stage, execution)
            execution = execution.model_copy(update={
                "stage_results": execution.stage_results + [result],
                "current_stage": stage.stage_id,
                "warnings": execution.warnings + result.warnings,
                "errors": execution.errors + result.errors,
            })
            self._store.save(execution)

            if result.status == "failed" and stage.required:
                execution = execution.model_copy(
                    update={"status": "failed", "completed_at": datetime.now(timezone.utc)}
                )
                self._store.save(execution)
                return execution

            completed_ids.add(stage.stage_id)

        execution = execution.model_copy(update={"status": "completed", "completed_at": datetime.now(timezone.utc)})
        self._store.save(execution)
        return execution

    # -- internal: human approval --------------------------------------------------------------

    def _run_human_approval(
        self, stage: WorkflowStageDefinition, execution: WorkflowExecution
    ) -> WorkflowExecution:
        if self._should_pause(stage, execution):
            pending = WorkflowStageResult(
                stage_id=stage.stage_id, stage_name=stage.name, status="awaiting_approval",
                started_at=datetime.now(timezone.utc),
            )
            return execution.model_copy(update={
                "status": "awaiting_approval",
                "current_stage": stage.stage_id,
                "stage_results": execution.stage_results + [pending],
            })

        skipped = WorkflowStageResult(
            stage_id=stage.stage_id, stage_name=stage.name, status="skipped",
            started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
        )
        return execution.model_copy(update={
            "stage_results": execution.stage_results + [skipped],
            "current_stage": stage.stage_id,
        })

    @staticmethod
    def _should_pause(stage: WorkflowStageDefinition, execution: WorkflowExecution) -> bool:
        if not stage.human_approval_required:
            return False
        if stage.approval_condition in (None, "always"):
            return True
        if stage.approval_condition == "on_blocking_finding":
            return WorkflowEngine._has_blocking_finding(execution)
        return False

    @staticmethod
    def _is_truthy(value: object) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return value.strip().lower() not in ("", "no", "false", "0", "unknown")
        if isinstance(value, list):
            return len(value) > 0
        return bool(value)

    @staticmethod
    def _has_blocking_finding(execution: WorkflowExecution) -> bool:
        for result in execution.stage_results:
            if any(item.get("blocking") for item in result.structured_output.get("findings", [])):
                return True
            if any(item.get("blocking") for item in result.structured_output.get("evidence_gaps", [])):
                return True
        return False

    @staticmethod
    def _record_approval(
        execution: WorkflowExecution, stage_id: str | None, decision: ApprovalDecision
    ) -> WorkflowExecution:
        updated_results = list(execution.stage_results)
        index = next((i for i, r in enumerate(updated_results) if r.stage_id == stage_id), None)
        if index is None:
            raise WorkflowEngineError(f"No pending approval stage found for execution '{execution.execution_id}'.")

        result = updated_results[index]
        structured_output = dict(result.structured_output)
        structured_output["approval"] = decision.model_dump(mode="json")
        updated_results[index] = result.model_copy(update={
            "structured_output": structured_output,
            "status": "completed",
            "completed_at": datetime.now(timezone.utc),
        })
        return execution.model_copy(update={"stage_results": updated_results})

    # -- internal: stage dispatch --------------------------------------------------------------

    def _run_stage_body(
        self, definition: WorkflowDefinition, stage: WorkflowStageDefinition, execution: WorkflowExecution
    ) -> WorkflowStageResult:
        if stage.stage_type == "validate_input":
            return self._run_validate_input(definition, stage, execution)
        if stage.stage_type == "advisor_review":
            return self._run_advisor_review(stage, execution)
        if stage.stage_type == "conflict_review":
            return self._run_conflict_review(stage, execution)
        if stage.stage_type == "executive_synthesis":
            return self._run_executive_synthesis(definition, stage, execution)
        if stage.stage_type == "final_report":
            return self._run_final_report(definition, stage, execution)
        raise WorkflowEngineError(f"Unhandled stage_type '{stage.stage_type}' for stage '{stage.stage_id}'.")

    def _run_validate_input(
        self, definition: WorkflowDefinition, stage: WorkflowStageDefinition, execution: WorkflowExecution
    ) -> WorkflowStageResult:
        started_at = datetime.now(timezone.utc)
        result = validate_input(definition, execution.inputs)
        if not result.valid:
            return WorkflowStageResult(
                stage_id=stage.stage_id, stage_name=stage.name, status="failed",
                started_at=started_at, completed_at=datetime.now(timezone.utc), errors=result.errors,
            )
        return WorkflowStageResult(
            stage_id=stage.stage_id, stage_name=stage.name, status="completed",
            started_at=started_at, completed_at=datetime.now(timezone.utc),
            structured_output={"evidence_gaps": [gap.model_dump(mode="json") for gap in result.evidence_gaps]},
        )

    def _run_advisor_review(
        self, stage: WorkflowStageDefinition, execution: WorkflowExecution
    ) -> WorkflowStageResult:
        started_at = datetime.now(timezone.utc)
        advisor = get_advisor(stage.advisor_name)
        question = stage.question_template.format_map(_SafeDict(execution.inputs))
        try:
            answer = advisor.ask(self._service, question)
        except (QuestionValidationError, ModelProviderError) as exc:
            return WorkflowStageResult(
                stage_id=stage.stage_id, stage_name=stage.name, status="failed",
                started_at=started_at, completed_at=datetime.now(timezone.utc),
                advisor_name=stage.advisor_name, errors=[str(exc)],
            )
        return WorkflowStageResult(
            stage_id=stage.stage_id, stage_name=stage.name, status="completed",
            started_at=started_at, completed_at=datetime.now(timezone.utc),
            advisor_name=stage.advisor_name, answer=answer.answer, citations=answer.citations,
            warnings=answer.warnings,
            diagnostics={
                "question": question,
                "sufficient_context": answer.sufficient_context,
                "model_provider": answer.diagnostics.model_provider,
                "model_name": answer.diagnostics.model_name,
                "total_duration_ms": answer.diagnostics.total_duration_ms,
            },
        )

    def _run_conflict_review(
        self, stage: WorkflowStageDefinition, execution: WorkflowExecution
    ) -> WorkflowStageResult:
        started_at = datetime.now(timezone.utc)
        findings = detect_conflicts(execution.stage_results)
        return WorkflowStageResult(
            stage_id=stage.stage_id, stage_name=stage.name, status="completed",
            started_at=started_at, completed_at=datetime.now(timezone.utc),
            structured_output={"findings": [finding.model_dump(mode="json") for finding in findings]},
        )

    def _run_executive_synthesis(
        self, definition: WorkflowDefinition, stage: WorkflowStageDefinition, execution: WorkflowExecution
    ) -> WorkflowStageResult:
        question = stage.question_template.format_map(_SafeDict(execution.inputs))
        findings = self._collect_findings(execution)
        evidence_gaps = self._collect_evidence_gaps(execution)
        approval_comments = self._collect_approval_comments(execution)
        advisor_stage_results = [r for r in execution.stage_results if r.advisor_name]

        return run_synthesis_stage(
            self._service.llm,
            stage_id=stage.stage_id, stage_name=stage.name, workflow_name=definition.name,
            question=question, report_sections=definition.output_template,
            stage_results=advisor_stage_results,
            review_findings=findings, evidence_gaps=evidence_gaps,
            conflicts=[finding for finding in findings if finding.category == "conflict"],
            approval_comments=approval_comments,
            temperature=self._rag_settings.llm_temperature,
            max_tokens=self._rag_settings.llm_max_output_tokens,
        )

    def _run_final_report(
        self, definition: WorkflowDefinition, stage: WorkflowStageDefinition, execution: WorkflowExecution
    ) -> WorkflowStageResult:
        started_at = datetime.now(timezone.utc)
        synthesis_stage_id = next(
            (s.stage_id for s in definition.stages if s.stage_type == "executive_synthesis"), None
        )
        synthesis_result = next(
            (r for r in execution.stage_results if r.stage_id == synthesis_stage_id), None
        )
        synthesis_answer = synthesis_result.answer if synthesis_result else None

        extra_sections: dict[str, str] = {}
        if definition.recommendation_rule is not None:
            evidence_gaps = self._collect_evidence_gaps(execution)
            findings = self._collect_findings(execution)
            extra_sections["Recommendation"] = definition.recommendation_rule(evidence_gaps, findings)

        report = build_final_report(
            definition, execution, synthesis_answer=synthesis_answer, extra_sections=extra_sections or None
        )

        return WorkflowStageResult(
            stage_id=stage.stage_id, stage_name=stage.name, status="completed",
            started_at=started_at, completed_at=datetime.now(timezone.utc),
            structured_output={"report_sections": report.sections},
            citations=dedupe_citations(execution.stage_results),
        )

    # -- internal: cross-stage aggregation --------------------------------------------------------------

    @staticmethod
    def _collect_findings(execution: WorkflowExecution) -> list[ReviewFinding]:
        return [
            ReviewFinding.model_validate(item)
            for result in execution.stage_results
            for item in result.structured_output.get("findings", [])
        ]

    @staticmethod
    def _collect_evidence_gaps(execution: WorkflowExecution) -> list[EvidenceGap]:
        return [
            EvidenceGap.model_validate(item)
            for result in execution.stage_results
            for item in result.structured_output.get("evidence_gaps", [])
        ]

    @staticmethod
    def _collect_approval_comments(execution: WorkflowExecution) -> str | None:
        comments = [
            result.structured_output["approval"]["comments"]
            for result in execution.stage_results
            if result.structured_output.get("approval", {}).get("comments")
        ]
        return "\n".join(comments) if comments else None


def _stage_by_id(definition: WorkflowDefinition, stage_id: str) -> WorkflowStageDefinition:
    for stage in definition.stages:
        if stage.stage_id == stage_id:
            return stage
    raise WorkflowEngineError(f"Workflow '{definition.workflow_id}' has no stage '{stage_id}'.")


def build_default_workflow_engine(
    rag_settings: RagSettings | None = None,
    retrieval_settings: RetrievalSettings | None = None,
    workflow_settings: WorkflowSettings | None = None,
) -> WorkflowEngine:
    rag_settings = rag_settings or RagSettings.from_env()
    workflow_settings = workflow_settings or WorkflowSettings.from_env()
    service = build_default_rag_service(rag_settings, retrieval_settings)
    store = WorkflowStore(workflow_settings.workflow_store_dir)
    return WorkflowEngine(service, store, rag_settings)
