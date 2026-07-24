"""AI Solution Review workflow definition (Milestone 6).

Stages: Validate AI Solution Input -> AI Engineering/Security/
Architecture/Testing/DevSecOps Advisor Review -> Conflict Review ->
Human Approval When High Risk (pauses only on a blocking finding/gap) ->
Executive Synthesis -> Final AI Solution Review Report.
"""

from __future__ import annotations

from app.workflows.definitions import WorkflowDefinition, WorkflowStageDefinition

INPUT_SCHEMA = {
    "use_case": {"type": "string", "required": True},
    "business_objective": {"type": "string", "required": True},
    "model_provider": {"type": "string", "required": True},
    "rag_usage": {"type": "string", "required": False},
    "agent_usage": {"type": "string", "required": False},
    "data_sources": {"type": "list", "required": False},
    "data_sensitivity": {
        "type": "enum",
        "required": True,
        "enum_values": ["Public", "Internal", "Confidential", "Restricted"],
    },
    "human_review_process": {
        "type": "string",
        "required": False,
        "evidence_gap": {
            "description": "No human review process described for AI-generated output.",
            "severity": "critical",
            "blocking": True,
        },
    },
    "evaluation_approach": {
        "type": "string",
        "required": False,
        "evidence_gap": {
            "description": "No evaluation approach described for this AI solution.",
            "severity": "high",
            "blocking": False,
        },
    },
    "deployment_model": {"type": "string", "required": False},
    "expected_users": {"type": "string", "required": False},
    "known_risks": {"type": "list", "required": False},
}

_QUESTION_TEMPLATE = (
    "Northstar is building an AI solution for: {use_case}, to achieve: {business_objective}. "
    "Model provider: {model_provider}. RAG usage: {rag_usage}. Agent usage: {agent_usage}. "
    "Data sources: {data_sources}. Data sensitivity: {data_sensitivity}. "
    "Human review process: {human_review_process}. Evaluation approach: {evaluation_approach}. "
    "Deployment model: {deployment_model}. Expected users: {expected_users}. "
    "Known risks: {known_risks}. "
    "Review this AI solution from your area of responsibility, citing the relevant Northstar "
    "standards it should be checked against."
)

STAGES = (
    WorkflowStageDefinition(
        stage_id="validate_ai_solution_input",
        name="Validate AI Solution Input",
        stage_type="validate_input",
    ),
    WorkflowStageDefinition(
        stage_id="ai_engineering_review",
        name="AI Engineering Advisor Review",
        stage_type="advisor_review",
        advisor_name="ai-engineering",
        depends_on=("validate_ai_solution_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="security_review",
        name="Security Advisor Review",
        stage_type="advisor_review",
        advisor_name="security",
        depends_on=("validate_ai_solution_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="architecture_review",
        name="Architecture Advisor Review",
        stage_type="advisor_review",
        advisor_name="architecture",
        depends_on=("validate_ai_solution_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="testing_review",
        name="Testing Advisor Review",
        stage_type="advisor_review",
        advisor_name="testing",
        depends_on=("validate_ai_solution_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="devsecops_review",
        name="DevSecOps Advisor Review",
        stage_type="advisor_review",
        advisor_name="devsecops",
        depends_on=("validate_ai_solution_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="conflict_review",
        name="Conflict Review",
        stage_type="conflict_review",
        depends_on=(
            "ai_engineering_review", "security_review", "architecture_review",
            "testing_review", "devsecops_review",
        ),
    ),
    WorkflowStageDefinition(
        stage_id="human_approval_high_risk",
        name="Human Approval When High Risk",
        stage_type="human_approval",
        required=False,
        depends_on=("conflict_review",),
        human_approval_required=True,
        approval_condition="on_blocking_finding",
    ),
    WorkflowStageDefinition(
        stage_id="executive_synthesis",
        name="Executive Synthesis",
        stage_type="executive_synthesis",
        depends_on=("human_approval_high_risk",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="final_ai_solution_report",
        name="Final AI Solution Review Report",
        stage_type="final_report",
        depends_on=("executive_synthesis",),
    ),
)

OUTPUT_TEMPLATE = (
    "Solution Summary",
    "Business Fit",
    "Architecture Assessment",
    "Grounding and Hallucination Risk",
    "Data Privacy and Security",
    "Prompt and Model Risk",
    "Evaluation Readiness",
    "Human Oversight",
    "DevSecOps and Deployment Controls",
    "Cost and Scalability",
    "Blocking Issues",
    "Required Actions",
    "Recommendation",
    "Sources",
)

WORKFLOW = WorkflowDefinition(
    workflow_id="ai_solution_review",
    name="AI Solution Review",
    version="1.0.0",
    description=(
        "Reviews a proposed AI solution for grounding/hallucination risk, data privacy, "
        "human oversight, and deployment controls, pausing for human approval only when a "
        "blocking risk is found."
    ),
    input_schema=INPUT_SCHEMA,
    stages=STAGES,
    output_template=OUTPUT_TEMPLATE,
)
