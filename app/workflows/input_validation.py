"""Structured input validation + evidence-gap detection for a workflow's
"Validate Input" stage (Milestone 6).

`WorkflowDefinition.input_schema` is a small, self-rolled dict format --
no external JSON Schema dependency:

    {
        "field_name": {
            "type": "string" | "list" | "enum",
            "required": True | False,
            "enum_values": [...],              # only for type == "enum"
            "evidence_gap": {                     # optional; only used
                "description": "...",                # when required=False
                "severity": "critical",               # and the field is
                "blocking": True,                       # actually missing
            },
        },
        ...
    }

Required-field violations are hard validation errors -- the stage fails
and the workflow halts before ever calling an advisor. Missing optional
fields with an `evidence_gap` entry are NOT validation errors: they
become `EvidenceGap` findings that flow into the final report and can
force a bounded recommendation (e.g. Production Readiness Review's
`INSUFFICIENT_EVIDENCE`) -- "do not allow polished model language to
hide missing evidence."
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.models.workflow import EvidenceGap
from app.workflows.definitions import WorkflowDefinition

MAX_INPUT_BYTES = 200_000
MAX_LIST_ITEMS = 200
VALID_FIELD_TYPES = {"string", "list", "enum"}


@dataclass(frozen=True)
class InputValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    evidence_gaps: list[EvidenceGap] = field(default_factory=list)


def validate_input(definition: WorkflowDefinition, raw_input: dict[str, Any]) -> InputValidationResult:
    schema = definition.input_schema
    errors: list[str] = []
    evidence_gaps: list[EvidenceGap] = []

    try:
        size = len(json.dumps(raw_input))
    except TypeError as exc:
        return InputValidationResult(valid=False, errors=[f"Input is not JSON-serializable: {exc}"])
    if size > MAX_INPUT_BYTES:
        errors.append(f"Input exceeds maximum size ({size} > {MAX_INPUT_BYTES} bytes).")

    for field_name, field_spec in schema.items():
        field_type = field_spec.get("type", "string")
        required = bool(field_spec.get("required", False))
        present = field_name in raw_input and raw_input[field_name] not in (None, "", [])

        if required and not present:
            errors.append(f"Missing required field '{field_name}'.")
            continue

        if not present:
            gap_spec = field_spec.get("evidence_gap")
            if gap_spec:
                evidence_gaps.append(
                    EvidenceGap(
                        field=field_name,
                        description=gap_spec.get("description", f"No {field_name} provided."),
                        severity=gap_spec.get("severity", "medium"),
                        blocking=bool(gap_spec.get("blocking", False)),
                    )
                )
            continue

        value = raw_input[field_name]

        if field_type == "enum":
            enum_values = field_spec.get("enum_values", [])
            if value not in enum_values:
                errors.append(f"Field '{field_name}' must be one of {enum_values}, got {value!r}.")
        elif field_type == "list":
            if not isinstance(value, list):
                errors.append(f"Field '{field_name}' must be a list, got {type(value).__name__}.")
            elif len(value) > MAX_LIST_ITEMS:
                errors.append(f"Field '{field_name}' has {len(value)} items, exceeding {MAX_LIST_ITEMS}.")
        elif field_type == "string":
            if not isinstance(value, str):
                errors.append(f"Field '{field_name}' must be a string, got {type(value).__name__}.")
        else:
            errors.append(f"Field '{field_name}' declares unsupported type '{field_type}'.")

    return InputValidationResult(valid=not errors, errors=errors, evidence_gaps=evidence_gaps)
