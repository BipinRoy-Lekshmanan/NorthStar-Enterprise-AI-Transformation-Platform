"""Architecture Review workflow definition (Milestone 6).

Stages: Validate Architecture Input -> Architecture/Security/Platform
Engineering/Testing Advisor Review -> Conflict Review -> Optional Human
Approval (always pauses, before synthesis) -> Executive Synthesis ->
Final Architecture Review Report.
"""

from __future__ import annotations

from app.workflows.definitions import WorkflowDefinition, WorkflowStageDefinition

INPUT_SCHEMA = {
    "solution_name": {"type": "string", "required": True},
    "business_objective": {"type": "string", "required": True},
    "architecture_description": {"type": "string", "required": True},
    "data_classification": {
        "type": "enum",
        "required": True,
        "enum_values": ["Public", "Internal", "Confidential", "Restricted"],
    },
    "deployment_target": {"type": "string", "required": True},
    "expected_volume": {"type": "string", "required": True},
    "known_constraints": {"type": "list", "required": False},
}

_QUESTION_TEMPLATE = (
    "Northstar is designing '{solution_name}' to achieve: {business_objective}. "
    "Architecture description: {architecture_description}. "
    "Data classification: {data_classification}. Deployment target: {deployment_target}. "
    "Expected volume: {expected_volume}. Known constraints: {known_constraints}. "
    "Review this architecture from your area of responsibility, citing the relevant Northstar "
    "principles or standards it should be checked against."
)

STAGES = (
    WorkflowStageDefinition(
        stage_id="validate_architecture_input",
        name="Validate Architecture Input",
        stage_type="validate_input",
    ),
    WorkflowStageDefinition(
        stage_id="architecture_review",
        name="Architecture Advisor Review",
        stage_type="advisor_review",
        advisor_name="architecture",
        depends_on=("validate_architecture_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="security_review",
        name="Security Advisor Review",
        stage_type="advisor_review",
        advisor_name="security",
        depends_on=("validate_architecture_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="platform_review",
        name="Platform Engineering Advisor Review",
        stage_type="advisor_review",
        advisor_name="platform-engineering",
        depends_on=("validate_architecture_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="testing_review",
        name="Testing Advisor Review",
        stage_type="advisor_review",
        advisor_name="testing",
        depends_on=("validate_architecture_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="conflict_review",
        name="Conflict Review",
        stage_type="conflict_review",
        depends_on=("architecture_review", "security_review", "platform_review", "testing_review"),
    ),
    WorkflowStageDefinition(
        stage_id="human_approval",
        name="Optional Human Approval",
        stage_type="human_approval",
        required=False,
        depends_on=("conflict_review",),
        human_approval_required=True,
        approval_condition="always",
    ),
    WorkflowStageDefinition(
        stage_id="executive_synthesis",
        name="Executive Synthesis",
        stage_type="executive_synthesis",
        depends_on=("human_approval",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="final_architecture_report",
        name="Final Architecture Review Report",
        stage_type="final_report",
        depends_on=("executive_synthesis",),
    ),
)

OUTPUT_TEMPLATE = (
    "Executive Summary",
    "Business and Technical Context",
    "Architecture Strengths",
    "Architecture Risks",
    "Security Considerations",
    "Platform and Operational Considerations",
    "Testing and Quality Considerations",
    "Architecture Principle Alignment",
    "Relevant ADRs and Standards",
    "Conflicts or Open Decisions",
    "Required Actions",
    "Recommendation",
    "Sources",
)

WORKFLOW = WorkflowDefinition(
    workflow_id="architecture_review",
    name="Architecture Review",
    version="1.0.0",
    description=(
        "Reviews a proposed solution architecture against Northstar's architecture, security, "
        "platform, and testing standards, cross-checked for conflicts, always pausing for human "
        "approval before the final synthesis."
    ),
    input_schema=INPUT_SCHEMA,
    stages=STAGES,
    output_template=OUTPUT_TEMPLATE,
)
