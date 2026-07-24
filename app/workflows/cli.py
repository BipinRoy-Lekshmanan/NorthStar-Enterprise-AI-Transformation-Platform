"""CLI for controlled enterprise workflow orchestration (Milestone 6).

    python -m app.workflows list
    python -m app.workflows describe production_readiness_review
    python -m app.workflows run production_readiness_review --input examples/workflows/*.json
    python -m app.workflows status <execution-id>
    python -m app.workflows approve <execution-id> --decision approve --comments "..."
    python -m app.workflows resume <execution-id>
    python -m app.workflows cancel <execution-id>

Pure formatting only -- no engine/persistence/business logic lives here
(see `app.workflows.engine`, `app.workflows.registry`, `app.workflows.store`).
Structured input always comes from a JSON file (`--input`), never pasted
inline on the command line.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.models.workflow import ApprovalDecision, EvidenceGap, ReviewFinding, WorkflowExecution
from app.workflows.definitions import WorkflowDefinition
from app.workflows.engine import WorkflowEngineError, build_default_workflow_engine
from app.workflows.registry import UnknownWorkflowError, get_workflow, list_workflows
from app.workflows.store import WorkflowStoreError
from app.workflows.synthesis import dedupe_citations

_SHOW_FLAGS = ("show_stages", "show_findings", "show_conflicts", "show_citations", "show_diagnostics")


def _collect_findings(execution: WorkflowExecution) -> list[ReviewFinding]:
    return [
        ReviewFinding.model_validate(item)
        for result in execution.stage_results
        for item in result.structured_output.get("findings", [])
    ]


def _collect_evidence_gaps(execution: WorkflowExecution) -> list[EvidenceGap]:
    return [
        EvidenceGap.model_validate(item)
        for result in execution.stage_results
        for item in result.structured_output.get("evidence_gaps", [])
    ]


def _format_workflow_list() -> str:
    lines = ["Available workflows:\n"]
    for definition in list_workflows():
        disabled = "  [disabled]" if not definition.enabled else ""
        lines.append(f"{definition.workflow_id}  (v{definition.version}){disabled}")
        lines.append(f"  {definition.name}")
        lines.append(f"  {definition.description}")
        lines.append("")
    return "\n".join(lines)


def _format_workflow_description(definition: WorkflowDefinition) -> str:
    lines = [f"{definition.name} ({definition.workflow_id}, v{definition.version})", "", definition.description, ""]

    lines.append("Stages:")
    stages_by_id = {stage.stage_id: stage for stage in definition.stages}
    for stage_id in definition.execution_order:
        stage = stages_by_id[stage_id]
        advisor = f" advisor={stage.advisor_name}" if stage.advisor_name else ""
        required = "" if stage.required else " (optional)"
        approval = (
            f" [pauses: {stage.approval_condition or 'always'}]" if stage.human_approval_required else ""
        )
        skip = f" [skipped unless '{stage.skip_unless_input_truthy}']" if stage.skip_unless_input_truthy else ""
        lines.append(f"  {stage.stage_id}: {stage.name} [{stage.stage_type}]{advisor}{required}{approval}{skip}")

    lines.append("")
    lines.append("Input fields:")
    for field_name, spec in definition.input_schema.items():
        requirement = "required" if spec.get("required") else "optional"
        lines.append(f"  {field_name} ({spec.get('type', 'string')}, {requirement})")

    lines.append("")
    lines.append("Report sections: " + ", ".join(definition.output_template))
    return "\n".join(lines)


def _format_execution_summary(execution: WorkflowExecution) -> str:
    lines = [
        f"Execution: {execution.execution_id}",
        f"Workflow:  {execution.workflow_id} (v{execution.workflow_version})",
        f"Status:    {execution.status}",
    ]
    if execution.current_stage:
        lines.append(f"Stage:     {execution.current_stage}")
    if execution.status == "awaiting_approval":
        lines.append("")
        lines.append(
            f"Awaiting human approval. Run: python -m app.workflows approve {execution.execution_id} "
            '--decision approve|reject|request_changes|cancel [--comments "..."]'
        )
    if execution.warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"  - {warning}" for warning in execution.warnings)
    if execution.errors:
        lines.append("")
        lines.append("Errors:")
        lines.extend(f"  - {error}" for error in execution.errors)
    return "\n".join(lines)


def _format_stages(execution: WorkflowExecution) -> str:
    lines = ["Stages:"]
    for result in execution.stage_results:
        advisor = f" advisor={result.advisor_name}" if result.advisor_name else ""
        lines.append(f"  [{result.status}] {result.stage_id} -- {result.stage_name}{advisor}")
    return "\n".join(lines)


def _format_findings(execution: WorkflowExecution) -> str:
    findings = _collect_findings(execution)
    gaps = _collect_evidence_gaps(execution)

    lines = ["Findings:"]
    if findings:
        lines.extend(
            f"  [{f.severity.upper()}{' [BLOCKING]' if f.blocking else ''}] {f.title}: {f.description}"
            for f in findings
        )
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("Evidence gaps:")
    for gap in gaps:
        blocking = " [BLOCKING]" if gap.blocking else ""
        lines.append(f"  [{gap.severity.upper()}{blocking}] {gap.field}: {gap.description}")
    if not gaps:
        lines.append("  (none)")
    return "\n".join(lines)


def _format_conflicts(execution: WorkflowExecution) -> str:
    conflicts = [finding for finding in _collect_findings(execution) if finding.category == "conflict"]
    lines = ["Conflicts:"]
    if not conflicts:
        lines.append("  (none detected)")
    for conflict in conflicts:
        lines.append(f"  {conflict.title} -- {', '.join(conflict.source_advisors)}")
        lines.append(f"    {conflict.description}")
    return "\n".join(lines)


def _format_citations(execution: WorkflowExecution) -> str:
    citations = dedupe_citations(execution.stage_results)
    lines = ["Sources:"]
    if not citations:
        lines.append("  (none)")
    for i, citation in enumerate(citations, 1):
        lines.append(
            f"  {i}. {citation.document_title or citation.source_file} -- "
            f"{citation.section_title or '(no section)'} ({citation.source_path})"
        )
    return "\n".join(lines)


def _format_diagnostics(execution: WorkflowExecution) -> str:
    lines = ["Diagnostics:"]
    for result in execution.stage_results:
        lines.append(f"  [{result.stage_id}] status={result.status}")
        for key, value in result.diagnostics.items():
            lines.append(f"    {key}: {value}")
        if result.started_at and result.completed_at:
            duration_ms = (result.completed_at - result.started_at).total_seconds() * 1000
            lines.append(f"    stage_duration_ms: {duration_ms:.1f}")
    return "\n".join(lines)


def _format_report(execution: WorkflowExecution) -> str:
    report_stage = next(
        (r for r in reversed(execution.stage_results) if "report_sections" in r.structured_output), None
    )
    if report_stage is None:
        return ""
    sections = report_stage.structured_output["report_sections"]
    lines = ["Final Report:", ""]
    for header, content in sections.items():
        lines.append(f"## {header}")
        lines.append(content.strip() if content and content.strip() else "(no content)")
        lines.append("")
    return "\n".join(lines)


def _render_output(execution: WorkflowExecution, args: argparse.Namespace) -> str:
    if args.output_format == "json":
        return json.dumps(execution.model_dump(mode="json"), indent=2)

    parts = [_format_execution_summary(execution)]
    if getattr(args, "show_stages", False):
        parts.append(_format_stages(execution))
    if getattr(args, "show_findings", False):
        parts.append(_format_findings(execution))
    if getattr(args, "show_conflicts", False):
        parts.append(_format_conflicts(execution))
    if getattr(args, "show_citations", False):
        parts.append(_format_citations(execution))
    if getattr(args, "show_diagnostics", False):
        parts.append(_format_diagnostics(execution))
    if execution.status == "completed":
        report_text = _format_report(execution)
        if report_text:
            parts.append(report_text)
    return "\n\n".join(parts)


def _emit(execution: WorkflowExecution, args: argparse.Namespace) -> None:
    output_text = _render_output(execution, args)
    if getattr(args, "output_file", None):
        args.output_file.write_text(output_text, encoding="utf-8")
        print(f"Output written to {args.output_file}")
    else:
        print(output_text)


def _add_show_flags(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument("--show-stages", action="store_true", help="List every stage's status")
    subparser.add_argument("--show-findings", action="store_true", help="List structured findings and evidence gaps")
    subparser.add_argument("--show-conflicts", action="store_true", help="List detected conflicts")
    subparser.add_argument("--show-citations", action="store_true", help="List deduped citations across all stages")
    subparser.add_argument("--show-diagnostics", action="store_true", help="Show per-stage diagnostics")
    subparser.add_argument("--output-format", choices=["text", "json"], default="text")
    subparser.add_argument("--output-file", type=Path, default=None, help="Write output to this file instead of stdout")


def main() -> None:
    from app.config.logging import configure_logging

    parser = argparse.ArgumentParser(description="Run controlled enterprise workflows over the Northstar knowledge base.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List available workflows")

    describe_parser = subparsers.add_parser("describe", help="Describe a workflow's stages and input schema")
    describe_parser.add_argument("workflow_id")

    run_parser = subparsers.add_parser("run", help="Run a workflow")
    run_parser.add_argument("workflow_id")
    run_parser.add_argument("--input", type=Path, required=True, help="Path to a JSON input file")
    _add_show_flags(run_parser)

    status_parser = subparsers.add_parser("status", help="Show an execution's current status")
    status_parser.add_argument("execution_id")
    _add_show_flags(status_parser)

    approve_parser = subparsers.add_parser("approve", help="Record a human approval decision and resume if approved")
    approve_parser.add_argument("execution_id")
    approve_parser.add_argument("--decision", required=True, choices=["approve", "reject", "request_changes", "cancel"])
    approve_parser.add_argument("--reviewer", default=None)
    approve_parser.add_argument("--comments", default=None)
    _add_show_flags(approve_parser)

    resume_parser = subparsers.add_parser("resume", help="Resume a running execution")
    resume_parser.add_argument("execution_id")
    _add_show_flags(resume_parser)

    cancel_parser = subparsers.add_parser("cancel", help="Cancel an execution")
    cancel_parser.add_argument("execution_id")

    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.command == "list":
        print(_format_workflow_list())
        return

    if args.command == "describe":
        try:
            definition = get_workflow(args.workflow_id)
        except UnknownWorkflowError as exc:
            print(f"Invalid workflow: {exc}")
            raise SystemExit(1) from None
        print(_format_workflow_description(definition))
        return

    configure_logging()
    engine = build_default_workflow_engine()

    if args.command == "run":
        try:
            raw_input = json.loads(args.input.read_text(encoding="utf-8"))
        except FileNotFoundError:
            print(f"Input file not found: {args.input}")
            raise SystemExit(1) from None
        except json.JSONDecodeError as exc:
            print(f"Input file is not valid JSON: {exc}")
            raise SystemExit(1) from None

        try:
            execution = engine.run(args.workflow_id, raw_input)
        except (UnknownWorkflowError, WorkflowEngineError) as exc:
            print(f"Workflow could not run: {exc}")
            raise SystemExit(1) from None

    elif args.command == "status":
        try:
            execution = engine.store.load(args.execution_id)
        except WorkflowStoreError as exc:
            print(str(exc))
            raise SystemExit(1) from None

    elif args.command == "approve":
        decision = ApprovalDecision(decision=args.decision, reviewer=args.reviewer, comments=args.comments)
        try:
            execution = engine.approve(args.execution_id, decision)
        except (WorkflowStoreError, WorkflowEngineError) as exc:
            print(str(exc))
            raise SystemExit(1) from None

    elif args.command == "resume":
        try:
            execution = engine.resume(args.execution_id)
        except (WorkflowStoreError, WorkflowEngineError) as exc:
            print(str(exc))
            raise SystemExit(1) from None

    elif args.command == "cancel":
        try:
            execution = engine.cancel(args.execution_id)
        except (WorkflowStoreError, WorkflowEngineError) as exc:
            print(str(exc))
            raise SystemExit(1) from None
        print(_format_execution_summary(execution))
        return

    else:  # pragma: no cover -- argparse `choices`/subparsers prevent this
        parser.error(f"Unknown command '{args.command}'")
        return

    _emit(execution, args)


if __name__ == "__main__":
    main()
