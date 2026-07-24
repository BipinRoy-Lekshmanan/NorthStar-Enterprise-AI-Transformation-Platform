"""Incident Review workflow definition (Milestone 6).

Stages: Validate Incident Input (also surfaces timeline/evidence
gaps) -> Incident Management/Release/Platform Engineering Advisor
Review -> Security Advisor Review When Applicable (skipped unless
security_related is truthy) -> Conflict Review -> Human Review
Checkpoint (always pauses, before corrective-action synthesis) ->
Corrective Action Synthesis -> Final Incident Review Report.

Never invents facts missing from the input: `suspected_root_cause` is
named "suspected" throughout (never promoted to "confirmed"), and a
missing timeline is a blocking evidence gap rather than something the
workflow fills in with a guess.
"""

from __future__ import annotations

from app.workflows.definitions import WorkflowDefinition, WorkflowStageDefinition

INPUT_SCHEMA = {
    "incident_title": {"type": "string", "required": True},
    "severity": {
        "type": "enum",
        "required": True,
        "enum_values": ["Sev-1", "Sev-2", "Sev-3", "Sev-4"],
    },
    "start_time": {"type": "string", "required": True},
    "end_time": {
        "type": "string",
        "required": False,
        "evidence_gap": {
            "description": "No incident end time recorded (incident may still be ongoing).",
            "severity": "medium",
            "blocking": False,
        },
    },
    "customer_impact": {"type": "string", "required": True},
    "systems_affected": {"type": "list", "required": True},
    "timeline": {
        "type": "list",
        "required": False,
        "evidence_gap": {
            "description": "No incident timeline provided.",
            "severity": "critical",
            "blocking": True,
        },
    },
    "detection_method": {"type": "string", "required": False},
    "containment_actions": {"type": "string", "required": False},
    "recovery_actions": {"type": "string", "required": False},
    "suspected_root_cause": {
        "type": "string",
        "required": False,
        "evidence_gap": {
            "description": "No suspected root cause identified yet.",
            "severity": "high",
            "blocking": False,
        },
    },
    "release_related": {"type": "enum", "required": False, "enum_values": ["yes", "no", "unknown"]},
    "security_related": {"type": "enum", "required": False, "enum_values": ["yes", "no", "unknown"]},
    "evidence": {
        "type": "list",
        "required": False,
        "evidence_gap": {
            "description": "No supporting evidence attached to this incident review.",
            "severity": "medium",
            "blocking": False,
        },
    },
}

_QUESTION_TEMPLATE = (
    "Northstar experienced an incident: '{incident_title}' (severity {severity}), starting "
    "{start_time} and ending {end_time}. Customer impact: {customer_impact}. "
    "Systems affected: {systems_affected}. Timeline: {timeline}. "
    "Detection method: {detection_method}. Containment actions taken: {containment_actions}. "
    "Recovery actions taken: {recovery_actions}. Suspected (not confirmed) root cause: "
    "{suspected_root_cause}. Release-related: {release_related}. Security-related: "
    "{security_related}. Supporting evidence: {evidence}. "
    "Review this incident from your area of responsibility, citing the relevant Northstar "
    "incident management standard. Only describe the root cause as 'suspected' -- never treat "
    "it as confirmed."
)

STAGES = (
    WorkflowStageDefinition(
        stage_id="validate_incident_input",
        name="Validate Incident Input",
        stage_type="validate_input",
    ),
    WorkflowStageDefinition(
        stage_id="incident_review",
        name="Incident Management Advisor Review",
        stage_type="advisor_review",
        advisor_name="incident-management",
        depends_on=("validate_incident_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="release_review",
        name="Release Advisor Review",
        stage_type="advisor_review",
        advisor_name="release",
        depends_on=("validate_incident_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="platform_review",
        name="Platform Engineering Advisor Review",
        stage_type="advisor_review",
        advisor_name="platform-engineering",
        depends_on=("validate_incident_input",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="security_review",
        name="Security Advisor Review When Applicable",
        stage_type="advisor_review",
        advisor_name="security",
        depends_on=("validate_incident_input",),
        question_template=_QUESTION_TEMPLATE,
        skip_unless_input_truthy="security_related",
    ),
    WorkflowStageDefinition(
        stage_id="conflict_review",
        name="Conflict Review",
        stage_type="conflict_review",
        depends_on=("incident_review", "release_review", "platform_review", "security_review"),
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
        stage_id="corrective_action_synthesis",
        name="Corrective Action Synthesis",
        stage_type="executive_synthesis",
        depends_on=("human_review_checkpoint",),
        question_template=_QUESTION_TEMPLATE,
    ),
    WorkflowStageDefinition(
        stage_id="final_incident_report",
        name="Final Incident Review Report",
        stage_type="final_report",
        depends_on=("corrective_action_synthesis",),
    ),
)

OUTPUT_TEMPLATE = (
    "Incident Summary",
    "Customer and Business Impact",
    "Timeline",
    "Detection and Response Assessment",
    "Containment and Recovery Assessment",
    "Root Cause Status",
    "Contributing Factors",
    "Release or Platform Findings",
    "Security Findings",
    "Corrective and Preventive Actions",
    "Owners and Target Dates",
    "Lessons Learned",
    "Sources",
)

WORKFLOW = WorkflowDefinition(
    workflow_id="incident_review",
    name="Incident Review",
    version="1.0.0",
    description=(
        "Reviews an incident's timeline, containment, recovery, and suspected root cause "
        "across incident management, release, platform, and (when applicable) security "
        "perspectives, always pausing for human review before corrective-action synthesis."
    ),
    input_schema=INPUT_SCHEMA,
    stages=STAGES,
    output_template=OUTPUT_TEMPLATE,
)
