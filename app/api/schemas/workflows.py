"""Request/response schemas for workflow endpoints (Milestone 7)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.api.services.workflow_service import WorkflowExample
from app.models.citation import Citation
from app.models.workflow import EvidenceGap, ReviewFinding, WorkflowExecution, WorkflowStageResult
from app.workflows.definitions import WorkflowDefinition


class WorkflowStageOut(BaseModel):
    stage_id: str
    name: str
    stage_type: str
    advisor_name: str | None
    required: bool
    depends_on: tuple[str, ...]
    human_approval_required: bool
    approval_condition: str | None
    skip_unless_input_truthy: str | None


class WorkflowSummaryOut(BaseModel):
    workflow_id: str
    name: str
    version: str
    description: str
    enabled: bool


class WorkflowDetailOut(WorkflowSummaryOut):
    stages: list[WorkflowStageOut]
    input_schema: dict[str, Any]
    output_template: tuple[str, ...]


def build_workflow_summary_out(definition: WorkflowDefinition) -> WorkflowSummaryOut:
    return WorkflowSummaryOut(
        workflow_id=definition.workflow_id, name=definition.name, version=definition.version,
        description=definition.description, enabled=definition.enabled,
    )


def build_workflow_detail_out(definition: WorkflowDefinition) -> WorkflowDetailOut:
    stages_by_id = {stage.stage_id: stage for stage in definition.stages}
    return WorkflowDetailOut(
        **build_workflow_summary_out(definition).model_dump(),
        stages=[
            WorkflowStageOut(
                stage_id=stage.stage_id, name=stage.name, stage_type=stage.stage_type,
                advisor_name=stage.advisor_name, required=stage.required, depends_on=stage.depends_on,
                human_approval_required=stage.human_approval_required,
                approval_condition=stage.approval_condition,
                skip_unless_input_truthy=stage.skip_unless_input_truthy,
            )
            for stage_id in definition.execution_order
            for stage in [stages_by_id[stage_id]]
        ],
        input_schema=definition.input_schema,
        output_template=definition.output_template,
    )


class WorkflowExampleOut(BaseModel):
    name: str
    inputs: dict[str, Any]


def build_workflow_example_out(example: WorkflowExample) -> WorkflowExampleOut:
    return WorkflowExampleOut(name=example.name, inputs=example.inputs)


class ExecuteWorkflowRequest(BaseModel):
    inputs: dict[str, Any]


class StageResultOut(BaseModel):
    stage_id: str
    stage_name: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    advisor_name: str | None
    answer: str | None
    warnings: list[str]
    errors: list[str]


def build_stage_result_out(result: WorkflowStageResult) -> StageResultOut:
    return StageResultOut(
        stage_id=result.stage_id, stage_name=result.stage_name, status=result.status,
        started_at=result.started_at, completed_at=result.completed_at, advisor_name=result.advisor_name,
        answer=result.answer, warnings=result.warnings, errors=result.errors,
    )


class ExecutionSummaryOut(BaseModel):
    execution_id: str
    workflow_id: str
    workflow_version: str
    status: str
    current_stage: str | None
    started_at: datetime
    completed_at: datetime | None


def build_execution_summary_out(execution: WorkflowExecution) -> ExecutionSummaryOut:
    return ExecutionSummaryOut(
        execution_id=execution.execution_id, workflow_id=execution.workflow_id,
        workflow_version=execution.workflow_version, status=execution.status,
        current_stage=execution.current_stage, started_at=execution.started_at,
        completed_at=execution.completed_at,
    )


class ExecutionDetailOut(ExecutionSummaryOut):
    inputs: dict[str, Any]
    stage_results: list[StageResultOut]
    findings: list[ReviewFinding]
    evidence_gaps: list[EvidenceGap]
    conflicts: list[ReviewFinding]
    citations: list[Citation]
    warnings: list[str]
    errors: list[str]


def build_execution_detail_out(
    execution: WorkflowExecution, *, findings: list[ReviewFinding], evidence_gaps: list[EvidenceGap],
    conflicts: list[ReviewFinding], citations: list[Citation],
) -> ExecutionDetailOut:
    return ExecutionDetailOut(
        **build_execution_summary_out(execution).model_dump(),
        inputs=execution.inputs,
        stage_results=[build_stage_result_out(result) for result in execution.stage_results],
        findings=findings, evidence_gaps=evidence_gaps, conflicts=conflicts, citations=citations,
        warnings=execution.warnings, errors=execution.errors,
    )


class WorkflowReportOut(BaseModel):
    execution_id: str
    workflow_id: str
    status: str
    sections: dict[str, str]
