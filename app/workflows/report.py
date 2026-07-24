"""Final report assembly for a completed workflow execution (Milestone 6).

Pure formatting/assembly -- no business logic, no LLM calls, no
retrieval. Mirrors the `_format_*` helper pattern in `app/rag/ask.py`,
but returns a real value (`WorkflowReport`) that the CLI then prints,
rather than printing directly, so `--output-format json` can also
consume it. This is the stage body for `stage_type == "final_report"`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.workflow import WorkflowExecution
from app.workflows.definitions import WorkflowDefinition
from app.workflows.synthesis import dedupe_citations


@dataclass(frozen=True)
class WorkflowReport:
    workflow_id: str
    workflow_name: str
    workflow_version: str
    execution_id: str
    status: str
    sections: dict[str, str] = field(default_factory=dict)


def build_final_report(
    definition: WorkflowDefinition,
    execution: WorkflowExecution,
    *,
    synthesis_answer: str | None,
    extra_sections: dict[str, str] | None = None,
) -> WorkflowReport:
    """Assemble a `WorkflowReport` covering every section in
    `definition.output_template`.

    Narrative sections are a best-effort split of `synthesis_answer` by
    matching each declared section name as a header line -- the synthesis
    prompt explicitly instructs the model to structure its answer this
    way. Nothing here invents new prose: if no headers are found, the
    entire synthesis answer is kept (under the first declared section)
    rather than dropped. The "Sources" section (if declared) is always
    computed deterministically from `execution`'s own citations, never
    from LLM text, so it can't be fabricated or lost to a formatting
    mismatch. `extra_sections` lets a specific workflow (e.g. Production
    Readiness Review's bounded GO/NO_GO recommendation) inject a
    deterministically-computed section without this module knowing any
    workflow-specific business rule.
    """
    sections = _split_synthesis_by_headers(synthesis_answer or "", list(definition.output_template))

    for header in definition.output_template:
        if header.strip().lower() == "sources" and not sections.get(header, "").strip():
            sections[header] = _render_sources_section(execution)

    if extra_sections:
        sections.update(extra_sections)

    return WorkflowReport(
        workflow_id=definition.workflow_id,
        workflow_name=definition.name,
        workflow_version=definition.version,
        execution_id=execution.execution_id,
        status=execution.status,
        sections=sections,
    )


def _split_synthesis_by_headers(text: str, headers: list[str]) -> dict[str, str]:
    if not headers:
        return {}

    normalized_headers = {header.strip().lower(): header for header in headers}
    sections: dict[str, list[str]] = {header: [] for header in headers}
    current: str | None = None
    matched_any = False

    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip().rstrip(":").strip().lower()
        if stripped in normalized_headers:
            current = normalized_headers[stripped]
            matched_any = True
            continue
        if current is not None:
            sections[current].append(line)

    if not matched_any:
        return {headers[0]: text.strip()}

    return {header: "\n".join(lines).strip() for header, lines in sections.items()}


def _render_sources_section(execution: WorkflowExecution) -> str:
    citations = dedupe_citations(execution.stage_results)
    if not citations:
        return "(no citations recorded)"
    lines = [
        f"- {citation.document_title or citation.source_file} — "
        f"{citation.section_title or '(no section)'} ({citation.source_path})"
        for citation in citations
    ]
    return "\n".join(lines)
