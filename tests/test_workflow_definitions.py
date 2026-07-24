"""Tests for `app.workflows.definitions` -- the workflow definition model
and its validation (cycle/duplicate/unsupported-type/missing-stage
rejection, deterministic execution order).
"""

import pytest

from app.workflows.definitions import (
    MAX_STAGES,
    WorkflowDefinition,
    WorkflowDefinitionError,
    WorkflowStageDefinition,
    validate_definition,
)


def _stage(stage_id, stage_type="validate_input", **kwargs):
    return WorkflowStageDefinition(stage_id=stage_id, name=stage_id, stage_type=stage_type, **kwargs)


def _definition(stages, **kwargs):
    return WorkflowDefinition(
        workflow_id="w", name="W", version="1.0.0", description="d",
        input_schema={}, stages=tuple(stages), output_template=(), **kwargs,
    )


def test_valid_definition_computes_execution_order():
    stages = (
        _stage("validate"),
        _stage(
            "review", stage_type="advisor_review", advisor_name="testing",
            depends_on=("validate",), question_template="q",
        ),
    )
    validated = validate_definition(_definition(stages))
    assert validated.execution_order == ("validate", "review")


def test_definition_with_no_stages_is_rejected():
    with pytest.raises(WorkflowDefinitionError, match="no stages"):
        validate_definition(_definition(()))


def test_duplicate_stage_id_is_rejected():
    stages = (_stage("validate"), _stage("validate"))
    with pytest.raises(WorkflowDefinitionError, match="duplicate stage_id"):
        validate_definition(_definition(stages))


def test_unknown_depends_on_target_is_rejected():
    stages = (_stage("validate"), _stage("review", stage_type="conflict_review", depends_on=("nonexistent",)))
    with pytest.raises(WorkflowDefinitionError, match="unknown stage"):
        validate_definition(_definition(stages))


def test_circular_dependency_is_rejected():
    stages = (
        _stage("validate"),
        _stage("a", stage_type="conflict_review", depends_on=("b",)),
        _stage("b", stage_type="conflict_review", depends_on=("a",)),
    )
    with pytest.raises(WorkflowDefinitionError, match="circular dependency"):
        validate_definition(_definition(stages))


def test_unsupported_stage_type_is_rejected():
    stages = (_stage("validate"), _stage("bogus", stage_type="not_a_real_type"))
    with pytest.raises(WorkflowDefinitionError, match="unsupported"):
        validate_definition(_definition(stages))


def test_advisor_review_without_advisor_name_is_rejected():
    stages = (_stage("validate"), _stage("review", stage_type="advisor_review", question_template="q"))
    with pytest.raises(WorkflowDefinitionError, match="advisor_name"):
        validate_definition(_definition(stages))


def test_advisor_review_without_question_template_is_rejected():
    stages = (_stage("validate"), _stage("review", stage_type="advisor_review", advisor_name="testing"))
    with pytest.raises(WorkflowDefinitionError, match="question_template"):
        validate_definition(_definition(stages))


def test_missing_validate_input_stage_is_rejected():
    stages = (_stage("conflict", stage_type="conflict_review"),)
    with pytest.raises(WorkflowDefinitionError, match="validate_input"):
        validate_definition(_definition(stages))


def test_stage_count_over_max_is_rejected():
    stages = [_stage("validate")] + [
        _stage(f"conflict_{i}", stage_type="conflict_review") for i in range(MAX_STAGES)
    ]
    with pytest.raises(WorkflowDefinitionError, match="MAX_STAGES"):
        validate_definition(_definition(stages))


def test_invalid_approval_condition_is_rejected():
    stages = (_stage("validate"), _stage("approval", stage_type="human_approval", approval_condition="bogus"))
    with pytest.raises(WorkflowDefinitionError, match="approval_condition"):
        validate_definition(_definition(stages))


def test_disabled_workflow_flag_is_preserved():
    validated = validate_definition(_definition((_stage("validate"),), enabled=False))
    assert validated.enabled is False


def test_execution_order_prefers_declaration_order_among_ties():
    # b and c both depend only on validate -- b declared first, so b should
    # come before c despite no explicit ordering constraint between them.
    stages = (
        _stage("validate"),
        _stage("c", stage_type="conflict_review", depends_on=("validate",)),
        _stage("b", stage_type="conflict_review", depends_on=("validate",)),
    )
    validated = validate_definition(_definition(stages))
    assert validated.execution_order == ("validate", "c", "b")


def test_real_registry_has_no_duplicate_workflow_ids():
    from app.workflows.registry import list_workflows

    ids = [workflow.workflow_id for workflow in list_workflows()]
    assert len(ids) == len(set(ids))


def test_real_registry_has_exactly_five_workflows():
    from app.workflows.registry import list_workflows

    assert len(list_workflows()) == 5
