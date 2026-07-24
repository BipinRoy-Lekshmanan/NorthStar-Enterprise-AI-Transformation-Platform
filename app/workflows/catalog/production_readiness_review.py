"""Production Readiness Review workflow definition (Milestone 6).

Stages: Validate Release Input -> Release/Testing/Security/DevSecOps/
Platform Engineering Advisor Review -> Conflict Review -> Blocking-Risk
Approval Checkpoint (pauses only if a blocking finding exists) -> Final
Readiness Synthesis -> Release Recommendation.

The workflow never deploys anything -- its only output is a bounded
recommendation string (`GO` / `GO_WITH_CONDITIONS` / `NO_GO` /
`INSUFFICIENT_EVIDENCE`), computed by `determine_recommendation()` below
and injected into the final report via `WorkflowDefinition.recommendation_rule`.
"""

from __future__ import annotations

from app.models.workflow import EvidenceGap, ReviewFinding
from app.workflows.definitions import WorkflowDefinition, WorkflowStageDefinition

INPUT_SCHEMA = {
    "release_name": {"type": "string", "required": True},
    "services_affected": {"type": "list", "required": True},
    "business_impact": {"type": "string", "required": True},
    "deployment_strategy": {
        "type": "enum",
        "required": True,
        "enum_values": ["canary", "blue_green", "rolling", "big_bang"],
    },
    "test_evidence": {
        "type": "string",
        "required": False,
        "evidence_gap": {
            "description": "No test evidence provided.",
            "severity": "high",
            "blocking": False,
        },
    },
    "security_evidence": {
        "type": "string",
        "required": False,
        "evidence_gap": {
            "description": "No security review evidence provided.",
            "severity": "high",
            "blocking": False,
        },
    },
    "performance_evidence": {
        "type": "string",
        "required": False,
        "evidence_gap": {
            "description": "No performance test evidence provided.",
            "severity": "medium",
            "blocking": False,
        },
    },
    "rollback_plan": {
        "type": "string",
        "required": False,
        "evidence_gap": {
            "description": "No rollback plan provided.",
            "severity": "critical",
            "blocking": True,
        },
    },
    "monitoring_plan": {
        "type": "string",
        "required": False,
        "evidence_gap": {
            "description": "No monitoring plan provided.",
            "severity": "medium",
            "blocking": False,
        },
    },
    "support_readiness": {
        "type": "string",
        "required": False,
        "evidence_gap": {
            "description": "No support readiness confirmation provided.",
            "severity": "medium",
            "blocking": False,
        },
    },
    "known_defects": {"type": "list", "required": False},
    "change_window": {"type": "string", "required": False},
}

_QUESTION_TEMPLATE = (
    "Northstar is preparing to release '{release_name}' (affecting {services_affected}) "
    "using a {deployment_strategy} deployment strategy during {change_window}. "
    "Business impact: {business_impact}. "
    "Test evidence: {test_evidence}. Security evidence: {security_evidence}. "
    "Performance evidence: {performance_evidence}. Rollback plan: {rollback_plan}. "
    "Monitoring plan: {monitoring_plan}. Support readiness: {support_readiness}. "
    "Known defects: {known_defects}. "
    "Assess whether this release is ready to proceed from your area of responsibility."
)

STAGES = (
    WorkflowStageDefinition(
        stage_id="validate_release_input",
        name="Validate Release Input",
        stage_type="validate_input",
    ),
    WorkflowStageDefinition(
        stage_id="release_review",
        name="Release Advisor Review",
        stage_type="advisor_review",
        advisor_name="release",
        depends_on=("validate_release_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="testing_review",
        name="Testing Advisor Review",
        stage_type="advisor_review",
        advisor_name="testing",
        depends_on=("validate_release_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="security_review",
        name="Security Advisor Review",
        stage_type="advisor_review",
        advisor_name="security",
        depends_on=("validate_release_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="devsecops_review",
        name="DevSecOps Advisor Review",
        stage_type="advisor_review",
        advisor_name="devsecops",
        depends_on=("validate_release_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="platform_review",
        name="Platform Engineering Advisor Review",
        stage_type="advisor_review",
        advisor_name="platform-engineering",
        depends_on=("validate_release_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="conflict_review",
        name="Conflict Review",
        stage_type="conflict_review",
        depends_on=(
            "release_review", "testing_review", "security_review",
            "devsecops_review", "platform_review",
        ),
    ),
    WorkflowStageDefinition(
        stage_id="blocking_risk_approval",
        name="Blocking-Risk Approval Checkpoint",
        stage_type="human_approval",
        required=False,
        depends_on=("conflict_review",),
        human_approval_required=True,
        approval_condition="on_blocking_finding",
    ),
    WorkflowStageDefinition(
        stage_id="readiness_synthesis",
        name="Final Readiness Synthesis",
        stage_type="executive_synthesis",
        depends_on=("blocking_risk_approval",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="release_recommendation",
        name="Release Recommendation",
        stage_type="final_report",
        depends_on=("readiness_synthesis",),
    ),
)

OUTPUT_TEMPLATE = (
    "Executive Summary",
    "Release Overview",
    "Test Evidence Assessment",
    "Security Evidence Assessment",
    "Performance Evidence Assessment",
    "Rollback and Monitoring Readiness",
    "Blocking Issues",
    "Required Actions",
    "Recommendation",
    "Sources",
)


def determine_recommendation(evidence_gaps: list[EvidenceGap], findings: list[ReviewFinding]) -> str:
    """Bounded GO/GO_WITH_CONDITIONS/NO_GO/INSUFFICIENT_EVIDENCE recommendation.

    A blocking evidence gap (e.g. no rollback plan) always wins over a
    blocking finding -- missing evidence means the review couldn't even
    be completed, which is a stronger statement than "we reviewed it and
    it's not ready."
    """
    if any(gap.blocking for gap in evidence_gaps):
        return "INSUFFICIENT_EVIDENCE"
    if any(finding.blocking for finding in findings):
        return "NO_GO"
    if any(finding.severity in ("critical", "high") for finding in findings):
        return "GO_WITH_CONDITIONS"
    return "GO"


WORKFLOW = WorkflowDefinition(
    workflow_id="production_readiness_review",
    name="Production Readiness Review",
    version="1.0.0",
    description=(
        "Assesses whether a release is ready to proceed: test, security, performance, "
        "rollback, monitoring, and support evidence, cross-checked for conflicts, with a "
        "bounded GO/GO_WITH_CONDITIONS/NO_GO/INSUFFICIENT_EVIDENCE recommendation. Never "
        "deploys anything -- output is a recommendation for a human to act on."
    ),
    input_schema=INPUT_SCHEMA,
    stages=STAGES,
    output_template=OUTPUT_TEMPLATE,
    recommendation_rule=determine_recommendation,
)
