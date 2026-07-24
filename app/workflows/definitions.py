"""Workflow definition model + validation (Milestone 6).

Workflow definitions are static, in-memory configuration -- never
persisted, never mutated at runtime -- so, same reasoning `Advisor` is a
frozen dataclass, `WorkflowStageDefinition`/`WorkflowDefinition` are
frozen dataclasses too, not pydantic. Persisted execution state lives in
`app.models.workflow` instead.

`validate_definition()` runs once, at registry-build time
(`app.workflows.registry`), never per-execution: it rejects duplicate
stage ids, unknown `depends_on` targets, cycles, unsupported
`stage_type`s, a missing `validate_input` stage, and an over-long stage
list, then computes one fixed topological `execution_order` that
`WorkflowEngine` walks on every run -- no dynamic scheduling, no
per-run re-sorting, no stage ever creates another stage.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

MAX_STAGES = 20

# A closed set -- rejected at registry-load time if a definition uses
# anything else. Each maps to exactly one stage-body module:
#   validate_input      -> app.workflows.input_validation
#   advisor_review       -> app.agents.registry.get_advisor(...).ask()
#   conflict_review       -> app.workflows.conflict_detection
#   human_approval         -> app.workflows.engine (pause/resume logic)
#   executive_synthesis     -> app.workflows.synthesis
#   final_report              -> app.workflows.report
VALID_STAGE_TYPES = {
    "validate_input",
    "advisor_review",
    "conflict_review",
    "human_approval",
    "executive_synthesis",
    "final_report",
}

VALID_APPROVAL_CONDITIONS = {"always", "on_blocking_finding"}


class WorkflowDefinitionError(ValueError):
    """Raised when a workflow definition is structurally invalid."""


@dataclass(frozen=True)
class WorkflowStageDefinition:
    stage_id: str
    name: str
    stage_type: str
    advisor_name: str | None = None
    required: bool = True
    depends_on: tuple[str, ...] = ()
    human_approval_required: bool = False
    # Only meaningful when human_approval_required=True. "always" (default
    # meaning when unset): pause unconditionally. "on_blocking_finding":
    # pause only if a blocking ReviewFinding exists among prior stages --
    # e.g. Production Readiness Review only pauses when Security or
    # Release reports a blocking risk, not on every run.
    approval_condition: str | None = None
    # When set, names an execution.inputs field that must be "truthy"
    # (non-empty string not in {"no", "false", "0"}, non-empty list, or
    # plain bool True) for this stage to actually run -- otherwise it is
    # marked "skipped" rather than executed. E.g. Incident Review's
    # "Security Advisor Review When Applicable" only runs when
    # security_related is truthy. Applies to any stage_type, checked
    # before dispatch.
    skip_unless_input_truthy: str | None = None
    # Required for advisor_review/executive_synthesis stages: the natural-
    # language question sent to the advisor/synthesis call, rendered from
    # `execution.inputs` via str.format_map (missing optional fields
    # render as "(not provided)" rather than raising).
    question_template: str | None = None
    # Reserved for future per-field stage wiring; the Milestone 6 engine
    # dispatches purely by stage_type and reads execution.inputs /
    # execution.stage_results directly, so these are currently metadata
    # only, kept for schema fidelity with the workflow spec.
    input_mapping: dict[str, str] = field(default_factory=dict)
    output_mapping: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int | None = None


@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_id: str
    name: str
    version: str
    description: str
    input_schema: dict[str, Any]
    stages: tuple[WorkflowStageDefinition, ...]
    output_template: tuple[str, ...]
    enabled: bool = True
    # Optional workflow-specific hook: (evidence_gaps, findings) -> a
    # bounded recommendation string (e.g. Production Readiness Review's
    # GO/GO_WITH_CONDITIONS/NO_GO/INSUFFICIENT_EVIDENCE). Kept off the
    # generic engine -- only the one or two workflows that need a bounded
    # enum recommendation set this; everyone else leaves it None and the
    # final report has no injected recommendation section.
    recommendation_rule: Callable[[list, list], str] | None = None
    # Populated by validate_definition() -- never set by hand when
    # constructing a catalog entry.
    execution_order: tuple[str, ...] = ()


def validate_definition(defn: WorkflowDefinition) -> WorkflowDefinition:
    """Validate `defn` and return a copy with `execution_order` populated.

    Raises `WorkflowDefinitionError` for any structural problem.
    """
    if not defn.stages:
        raise WorkflowDefinitionError(f"Workflow '{defn.workflow_id}' has no stages.")

    if len(defn.stages) > MAX_STAGES:
        raise WorkflowDefinitionError(
            f"Workflow '{defn.workflow_id}' has {len(defn.stages)} stages, "
            f"exceeding MAX_STAGES={MAX_STAGES}."
        )

    seen_ids: set[str] = set()
    for stage in defn.stages:
        if stage.stage_id in seen_ids:
            raise WorkflowDefinitionError(
                f"Workflow '{defn.workflow_id}' has a duplicate stage_id '{stage.stage_id}'."
            )
        seen_ids.add(stage.stage_id)

        if stage.stage_type not in VALID_STAGE_TYPES:
            raise WorkflowDefinitionError(
                f"Workflow '{defn.workflow_id}' stage '{stage.stage_id}' has unsupported "
                f"stage_type '{stage.stage_type}'; must be one of {sorted(VALID_STAGE_TYPES)}."
            )

        if stage.stage_type == "advisor_review" and not stage.advisor_name:
            raise WorkflowDefinitionError(
                f"Workflow '{defn.workflow_id}' stage '{stage.stage_id}' is stage_type "
                "'advisor_review' but has no advisor_name."
            )

        if stage.stage_type in ("advisor_review", "executive_synthesis") and not stage.question_template:
            raise WorkflowDefinitionError(
                f"Workflow '{defn.workflow_id}' stage '{stage.stage_id}' is stage_type "
                f"'{stage.stage_type}' but has no question_template."
            )

        if stage.approval_condition is not None and stage.approval_condition not in VALID_APPROVAL_CONDITIONS:
            raise WorkflowDefinitionError(
                f"Workflow '{defn.workflow_id}' stage '{stage.stage_id}' has unsupported "
                f"approval_condition '{stage.approval_condition}'; must be one of "
                f"{sorted(VALID_APPROVAL_CONDITIONS)}."
            )

    if not any(stage.stage_type == "validate_input" for stage in defn.stages):
        raise WorkflowDefinitionError(f"Workflow '{defn.workflow_id}' has no 'validate_input' stage.")

    for stage in defn.stages:
        for dep in stage.depends_on:
            if dep not in seen_ids:
                raise WorkflowDefinitionError(
                    f"Workflow '{defn.workflow_id}' stage '{stage.stage_id}' depends_on "
                    f"unknown stage '{dep}'."
                )

    execution_order = _topological_order(defn)
    return dataclasses.replace(defn, execution_order=execution_order)


def _topological_order(defn: WorkflowDefinition) -> tuple[str, ...]:
    """Deterministic topological sort: among stages whose dependencies are
    already satisfied, always picks the one declared earliest in
    `defn.stages` -- so execution_order matches declaration order whenever
    dependencies don't force otherwise. O(n^2), fine at MAX_STAGES=20.
    """
    stage_ids = [stage.stage_id for stage in defn.stages]
    depends_on = {stage.stage_id: set(stage.depends_on) for stage in defn.stages}

    order: list[str] = []
    remaining = set(stage_ids)

    while remaining:
        ready = [sid for sid in stage_ids if sid in remaining and depends_on[sid] <= set(order)]
        if not ready:
            raise WorkflowDefinitionError(
                f"Workflow '{defn.workflow_id}' has a circular dependency involving "
                f"stages {sorted(remaining)}."
            )
        next_stage = ready[0]
        order.append(next_stage)
        remaining.discard(next_stage)

    return tuple(order)
