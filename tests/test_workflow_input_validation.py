"""Tests for `app.workflows.input_validation` -- schema-driven input
validation and evidence-gap detection.
"""

from app.workflows.definitions import WorkflowDefinition
from app.workflows.input_validation import MAX_INPUT_BYTES, validate_input

SCHEMA = {
    "release_name": {"type": "string", "required": True},
    "deployment_strategy": {
        "type": "enum", "required": True, "enum_values": ["canary", "blue_green", "rolling"],
    },
    "rollback_plan": {
        "type": "string", "required": False,
        "evidence_gap": {"description": "No rollback plan provided.", "severity": "critical", "blocking": True},
    },
    "known_defects": {"type": "list", "required": False},
}


def _definition():
    return WorkflowDefinition(
        workflow_id="w", name="W", version="1.0.0", description="d",
        input_schema=SCHEMA, stages=(), output_template=(),
    )


def test_valid_input_passes_with_no_errors_or_gaps():
    result = validate_input(
        _definition(),
        {"release_name": "r1", "deployment_strategy": "canary", "rollback_plan": "rollback via helm", "known_defects": []},
    )
    assert result.valid is True
    assert result.errors == []
    assert result.evidence_gaps == []


def test_missing_required_field_is_an_error():
    result = validate_input(_definition(), {"deployment_strategy": "canary"})
    assert result.valid is False
    assert any("release_name" in e for e in result.errors)


def test_invalid_enum_value_is_an_error():
    result = validate_input(_definition(), {"release_name": "r1", "deployment_strategy": "bogus"})
    assert result.valid is False
    assert any("deployment_strategy" in e for e in result.errors)


def test_wrong_type_for_list_field_is_an_error():
    result = validate_input(
        _definition(), {"release_name": "r1", "deployment_strategy": "canary", "known_defects": "not a list"}
    )
    assert result.valid is False
    assert any("known_defects" in e for e in result.errors)


def test_missing_optional_field_with_evidence_gap_produces_a_gap_not_an_error():
    result = validate_input(_definition(), {"release_name": "r1", "deployment_strategy": "canary"})
    assert result.valid is True
    assert len(result.evidence_gaps) == 1
    gap = result.evidence_gaps[0]
    assert gap.field == "rollback_plan"
    assert gap.blocking is True
    assert gap.severity == "critical"


def test_missing_optional_field_without_evidence_gap_produces_no_gap():
    result = validate_input(
        _definition(), {"release_name": "r1", "deployment_strategy": "canary", "rollback_plan": "yes"}
    )
    assert result.evidence_gaps == []


def test_oversized_input_is_rejected():
    huge_value = "x" * (MAX_INPUT_BYTES + 1000)
    result = validate_input(
        _definition(), {"release_name": huge_value, "deployment_strategy": "canary"}
    )
    assert result.valid is False
    assert any("exceeds maximum size" in e for e in result.errors)


def test_malformed_non_serializable_input_is_rejected():
    class Unserializable:
        pass

    result = validate_input(_definition(), {"release_name": Unserializable(), "deployment_strategy": "canary"})
    assert result.valid is False
    assert any("not JSON-serializable" in e for e in result.errors)
