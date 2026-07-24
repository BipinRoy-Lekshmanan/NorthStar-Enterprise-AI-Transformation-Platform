"""Executive AI Transformation Assessment workflow definition (Milestone 6).

Stages: Validate Transformation Input -> Executive AI Transformation/AI
Engineering/Developer Experience/Platform Engineering/Security Advisor
-> Conflict Review -> Human Review Checkpoint (always pauses, before
roadmap synthesis) -> Roadmap Synthesis -> Final Executive Assessment.
"""

from __future__ import annotations

from app.workflows.definitions import WorkflowDefinition, WorkflowStageDefinition

INPUT_SCHEMA = {
    "business_priorities": {"type": "list", "required": True},
    "current_ai_capabilities": {"type": "string", "required": True},
    "current_engineering_metrics": {
        "type": "string",
        "required": False,
        "evidence_gap": {
            "description": "No current engineering metrics provided.",
            "severity": "medium",
            "blocking": False,
        },
    },
    "adoption_challenges": {"type": "list", "required": False},
    "technology_constraints": {"type": "list", "required": False},
    "governance_maturity": {
        "type": "enum",
        "required": False,
        "enum_values": ["initial", "developing", "defined", "managed", "optimizing"],
        "evidence_gap": {
            "description": "Governance maturity has not been assessed.",
            "severity": "high",
            "blocking": False,
        },
    },
    "budget_constraints": {"type": "string", "required": False},
    "target_timeline": {"type": "string", "required": True},
    "regulatory_considerations": {"type": "list", "required": False},
    "desired_business_outcomes": {"type": "list", "required": True},
}

_QUESTION_TEMPLATE = (
    "Northstar's business priorities are: {business_priorities}. Current AI capabilities: "
    "{current_ai_capabilities}. Current engineering metrics: {current_engineering_metrics}. "
    "Adoption challenges: {adoption_challenges}. Technology constraints: {technology_constraints}. "
    "Governance maturity: {governance_maturity}. Budget constraints: {budget_constraints}. "
    "Target timeline: {target_timeline}. Regulatory considerations: {regulatory_considerations}. "
    "Desired business outcomes: {desired_business_outcomes}. "
    "Assess Northstar's AI transformation readiness from your area of responsibility, framed for "
    "an executive audience."
)

STAGES = (
    WorkflowStageDefinition(
        stage_id="validate_transformation_input",
        name="Validate Transformation Input",
        stage_type="validate_input",
    ),
    WorkflowStageDefinition(
        stage_id="executive_transformation_review",
        name="Executive AI Transformation Advisor",
        stage_type="advisor_review",
        advisor_name="executive-ai-transformation",
        depends_on=("validate_transformation_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="ai_engineering_review",
        name="AI Engineering Advisor",
        stage_type="advisor_review",
        advisor_name="ai-engineering",
        depends_on=("validate_transformation_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="developer_experience_review",
        name="Developer Experience Advisor",
        stage_type="advisor_review",
        advisor_name="developer-experience",
        depends_on=("validate_transformation_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="platform_review",
        name="Platform Engineering Advisor",
        stage_type="advisor_review",
        advisor_name="platform-engineering",
        depends_on=("validate_transformation_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="security_review",
        name="Security Advisor",
        stage_type="advisor_review",
        advisor_name="security",
        depends_on=("validate_transformation_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="conflict_review",
        name="Conflict Review",
        stage_type="conflict_review",
        depends_on=(
            "executive_transformation_review", "ai_engineering_review",
            "developer_experience_review", "platform_review", "security_review",
        ),
    ),
    WorkflowStageDefinition(
        stage_id="human_review_checkpoint",
        name="Human Review Checkpoint",
        stage_type="human_approval",
        required=False,
        depends_on=("conflict_review",),
        human_approval_required=True,
        approval_condition="always",
    ),
    WorkflowStageDefinition(
        stage_id="roadmap_synthesis",
        name="Roadmap Synthesis",
        stage_type="executive_synthesis",
        depends_on=("human_review_checkpoint",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="final_executive_assessment",
        name="Final Executive Assessment",
        stage_type="final_report",
        depends_on=("roadmap_synthesis",),
    ),
)

OUTPUT_TEMPLATE = (
    "Executive Summary",
    "Current-State Assessment",
    "AI Maturity Assessment",
    "Business Value Opportunities",
    "Technology and Platform Gaps",
    "Operating Model Gaps",
    "Governance and Risk Gaps",
    "Developer Adoption Considerations",
    "12-Month Priorities",
    "24-Month Roadmap",
    "KPIs and Outcome Measures",
    "Investment Themes",
    "Major Risks",
    "Executive Decisions Required",
    "Sources",
)

WORKFLOW = WorkflowDefinition(
    workflow_id="executive_ai_transformation_assessment",
    name="Executive AI Transformation Assessment",
    version="1.0.0",
    description=(
        "Assesses Northstar's AI transformation readiness across strategy, engineering, "
        "developer experience, platform, and security, producing a 12/24-month roadmap for "
        "executive decision-making. Always pauses for human review before the roadmap is "
        "synthesized."
    ),
    input_schema=INPUT_SCHEMA,
    stages=STAGES,
    output_template=OUTPUT_TEMPLATE,
)
