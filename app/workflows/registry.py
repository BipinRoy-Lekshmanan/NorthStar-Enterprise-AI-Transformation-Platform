"""Static workflow registry (Milestone 6).

An explicit tuple of `WorkflowDefinition`s -- not dynamic
plugin-discovery, matching `app.agents.registry`'s "auditable at a
glance, adding one more workflow is one file + one line here" pattern.
Every definition is validated eagerly at import time via
`validate_definition()` -- a malformed workflow (duplicate stage id,
cycle, unsupported stage type, ...) fails fast at process startup,
never at first use.
"""

from __future__ import annotations

from app.workflows.catalog.ai_solution_review import WORKFLOW as AI_SOLUTION_REVIEW
from app.workflows.catalog.architecture_review import WORKFLOW as ARCHITECTURE_REVIEW
from app.workflows.catalog.executive_ai_transformation_assessment import (
    WORKFLOW as EXECUTIVE_AI_TRANSFORMATION_ASSESSMENT,
)
from app.workflows.catalog.incident_review import WORKFLOW as INCIDENT_REVIEW
from app.workflows.catalog.production_readiness_review import WORKFLOW as PRODUCTION_READINESS_REVIEW
from app.workflows.definitions import WorkflowDefinition, validate_definition

_WORKFLOWS: tuple[WorkflowDefinition, ...] = (
    validate_definition(ARCHITECTURE_REVIEW),
    validate_definition(AI_SOLUTION_REVIEW),
    validate_definition(PRODUCTION_READINESS_REVIEW),
    validate_definition(INCIDENT_REVIEW),
    validate_definition(EXECUTIVE_AI_TRANSFORMATION_ASSESSMENT),
)

WORKFLOW_REGISTRY: dict[str, WorkflowDefinition] = {workflow.workflow_id: workflow for workflow in _WORKFLOWS}


class UnknownWorkflowError(KeyError):
    """Raised when a workflow id doesn't match any registered workflow."""


def get_workflow(workflow_id: str) -> WorkflowDefinition:
    try:
        return WORKFLOW_REGISTRY[workflow_id]
    except KeyError:
        available = ", ".join(sorted(WORKFLOW_REGISTRY))
        raise UnknownWorkflowError(f"Unknown workflow '{workflow_id}'. Available: {available}") from None


def list_workflows() -> list[WorkflowDefinition]:
    return list(_WORKFLOWS)
