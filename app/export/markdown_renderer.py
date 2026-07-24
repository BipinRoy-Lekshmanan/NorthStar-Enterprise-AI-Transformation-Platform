"""Markdown export rendering (Milestone 7).

Pure formatting over the envelope dicts from `app.export.common` --
same discipline as `app.workflows.report`/`app.workflows.cli`'s
`_format_*` helpers: no business logic, no LLM calls, no retrieval.
"""

from __future__ import annotations

from typing import Any


def _render_citations(citations: list[dict[str, Any]]) -> list[str]:
    lines = []
    for i, citation in enumerate(citations, 1):
        title = citation.get("document_title") or citation.get("source_file", "unknown source")
        section = citation.get("section_title") or "(no section)"
        lines.append(f"{i}. {title} -- {section}")
    return lines


def render_query_answer_markdown(envelope: dict[str, Any]) -> str:
    lines = [f"# {envelope['title']}", "", f"_Generated: {envelope['generated_at']}_", ""]
    lines += ["## Question", "", envelope["question"], ""]
    lines += ["## Answer", "", envelope["answer"], ""]

    if not envelope["sufficient_context"]:
        lines += ["> **Note:** the knowledge base did not contain sufficient context for this question.", ""]

    routing = envelope.get("routing")
    if routing:
        lines += [
            "## Routing", "",
            f"Primary advisor: {routing['primary_advisor']} (confidence: {routing['confidence']:.2f})",
        ]
        if routing.get("supporting_advisors"):
            lines.append(f"Supporting advisors: {', '.join(routing['supporting_advisors'])}")
        lines.append("")

    if envelope["citations"]:
        lines += ["## Sources", "", *_render_citations(envelope["citations"]), ""]

    if envelope["conflicts"]:
        lines += ["## Conflicts", "", *[f"- {c}" for c in envelope["conflicts"]], ""]

    if envelope["warnings"]:
        lines += ["## Warnings", "", *[f"- {w}" for w in envelope["warnings"]], ""]

    lines += ["---", "", envelope["disclaimer"]]
    return "\n".join(lines)


def render_workflow_report_markdown(envelope: dict[str, Any]) -> str:
    lines = [
        f"# {envelope['title']}", "",
        f"_Generated: {envelope['generated_at']}_", "",
        f"Execution: `{envelope['execution_id']}` -- Status: **{envelope['status']}**", "",
    ]

    for header, content in envelope["sections"].items():
        lines += [f"## {header}", "", content.strip() if content and content.strip() else "(no content)", ""]

    if envelope["findings"]:
        lines += ["## Findings", ""]
        for finding in envelope["findings"]:
            blocking = " **[BLOCKING]**" if finding.get("blocking") else ""
            lines.append(f"- [{finding['severity'].upper()}{blocking}] {finding['title']}: {finding['description']}")
        lines.append("")

    if envelope["evidence_gaps"]:
        lines += ["## Evidence Gaps", ""]
        for gap in envelope["evidence_gaps"]:
            blocking = " **[BLOCKING]**" if gap.get("blocking") else ""
            lines.append(f"- [{gap['severity'].upper()}{blocking}] {gap['field']}: {gap['description']}")
        lines.append("")

    if envelope["conflicts"]:
        lines += ["## Conflicts", ""]
        for conflict in envelope["conflicts"]:
            lines.append(f"- {conflict['title']} -- {', '.join(conflict.get('source_advisors', []))}")
        lines.append("")

    if envelope["citations"]:
        lines += ["## Sources", "", *_render_citations(envelope["citations"]), ""]

    lines += ["---", "", envelope["disclaimer"]]
    return "\n".join(lines)
