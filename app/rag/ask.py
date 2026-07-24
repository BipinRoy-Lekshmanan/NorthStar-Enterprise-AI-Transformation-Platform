"""CLI entry point for the grounded RAG assistant.

    python -m app.rag.ask "How should a Sev-1 incident be handled?"
    python -m app.rag.ask "..." --advisor testing
    python -m app.rag.ask "..." --auto-route
    python -m app.rag.ask --list-advisors

Pure formatting only -- no prompt text, business logic, or citation
parsing lives here (see `app.rag.pipeline`, `app.config.prompt_config`,
`app.rag.citation_engine`, `app.agents.base_agent`, `app.agents.router`,
`app.agents.orchestrator`). `--show-context`/`--show-prompts` are wired
via optional callback hooks on `RagService.ask()` so the debug-only
content never has to pass through (or leak into) the `RagAnswer` model.
`--advisor` selection is manual; `--auto-route` (Milestone 5) instead
routes deterministically to the best advisor(s) via `AdvisorOrchestrator`
-- the two flags are mutually exclusive.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys

from app.agents.orchestrator import ConsolidatedAdvisorResponse, build_default_orchestrator
from app.agents.registry import UnknownAdvisorError, get_advisor, list_advisors
from app.agents.router import RoutingDecision
from app.config.prompt_config import RagPrompt
from app.config.settings import RagSettings
from app.models.response import RagAnswer
from app.rag.context_builder import ContextBuildResult
from app.rag.pipeline import QuestionValidationError, build_default_rag_service
from app.services.llm_service import ModelProviderError


def _format_answer(answer: RagAnswer) -> str:
    lines = [f"Question:\n{answer.question}\n", f"Answer:\n{answer.answer}\n"]

    if answer.warnings:
        lines.append("Warnings:")
        lines.extend(f"  - {w}" for w in answer.warnings)
        lines.append("")

    if answer.citations:
        lines.append("Sources:")
        for i, c in enumerate(answer.citations, 1):
            lines.append(f"{i}. {c.document_title or c.source_file} — {c.section_title or '(no section)'}")
            lines.append(f"   File: {c.source_path}")
            lines.append(f"   Score: {c.score:.2f}")
        lines.append("")
    elif answer.sufficient_context:
        lines.append("Sources: (none cited)\n")

    return "\n".join(lines)


def _format_diagnostics(answer: RagAnswer) -> str:
    d = answer.diagnostics
    lines = [
        "Diagnostics:",
        f"  request_id:             {d.request_id}",
        f"  sufficient_context:     {answer.sufficient_context}",
        f"  retrieval_duration_ms:  {d.retrieval_duration_ms:.1f}",
        f"    embed_duration_ms:    {d.embed_duration_ms:.1f}",
        f"    search_duration_ms:   {d.search_duration_ms:.1f}",
        f"  retrieved_chunk_count:  {d.retrieved_chunk_count}",
        f"  context_chunk_count:    {d.context_chunk_count}",
        f"  chunks_excluded:        {d.chunks_excluded}",
        f"  highest_retrieval_score:{d.highest_retrieval_score}",
        f"  model_provider:         {d.model_provider}",
        f"  model_name:             {d.model_name}",
        f"  model_latency_ms:       {d.model_latency_ms}",
        f"  input_tokens:           {d.input_tokens}",
        f"  output_tokens:          {d.output_tokens}",
        f"  prompt_version:         {d.prompt_version}",
        f"  total_duration_ms:      {d.total_duration_ms:.1f}",
    ]
    return "\n".join(lines)


def _format_context(context_result: ContextBuildResult) -> str:
    lines = [f"Context ({len(context_result.blocks)} block(s), {context_result.total_characters} chars, "
              f"{context_result.excluded_count} excluded {context_result.excluded_reasons}):\n"]
    for block in context_result.blocks:
        chunk = block.chunk
        lines.append(f"[{block.source_id}] score={block.score:.3f} {chunk.source_path}")
        lines.append(f"  Section: {chunk.section_title or '(no section)'}")
        lines.append(f"  {chunk.text.strip()}\n")
    return "\n".join(lines)


def _format_prompt(prompt: RagPrompt) -> str:
    return (
        f"Prompt (version={prompt.version}):\n\n"
        f"--- system ---\n{prompt.system}\n"
        f"--- user ---\n{prompt.user}\n"
    )


def _format_advisor_list() -> str:
    lines = ["Available advisors:\n"]
    for advisor in list_advisors():
        lines.append(f"{advisor.advisor_id}")
        lines.append(f"  {advisor.display_name}")
        lines.append(f"  {advisor.description}")
        if advisor.default_filters:
            lines.append(f"  Default filters: {advisor.default_filters}")
        lines.append("")
    return "\n".join(lines)


def _format_routing(routing: RoutingDecision) -> str:
    lines = [
        "Routing:",
        f"  primary_advisor:      {routing.primary_advisor}",
        f"  supporting_advisors:  {routing.supporting_advisors or '(none)'}",
        f"  confidence:           {routing.confidence:.3f}",
        f"  fallback_used:        {routing.fallback_used}",
        f"  detected_domains:     {routing.detected_domains or '(none)'}",
        f"  rationale:            {routing.rationale}",
        "",
    ]
    return "\n".join(lines)


def _format_consolidated_answer(response: ConsolidatedAdvisorResponse) -> str:
    lines = [f"Question:\n{response.question}\n", f"Answer:\n{response.answer}\n"]

    if response.warnings:
        lines.append("Warnings:")
        lines.extend(f"  - {w}" for w in response.warnings)
        lines.append("")

    if response.citations:
        lines.append("Sources:")
        for i, c in enumerate(response.citations, 1):
            lines.append(f"{i}. {c.document_title or c.source_file} — {c.section_title or '(no section)'}")
            lines.append(f"   File: {c.source_path}")
            lines.append(f"   Score: {c.score:.2f}")
        lines.append("")
    elif response.primary_answer.sufficient_context:
        lines.append("Sources: (none cited)\n")

    return "\n".join(lines)


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def _format_consolidated_diagnostics(response: ConsolidatedAdvisorResponse) -> str:
    lines = ["Diagnostics:", "", f"  [primary: {response.routing.primary_advisor}]"]
    lines.append(_indent(_format_diagnostics(response.primary_answer)))
    for advisor_id, answer in zip(response.routing.supporting_advisors, response.supporting_answers):
        lines.append(f"  [supporting: {advisor_id}]")
        lines.append(_indent(_format_diagnostics(answer)))
    lines.append("  [synthesis]")
    if response.synthesized:
        lines.append(f"    provider:    {response.synthesis_provider}")
        lines.append(f"    model:       {response.synthesis_model}")
        lines.append(f"    latency_ms:  {response.synthesis_latency_ms:.1f}")
    else:
        lines.append("    (not performed -- zero or one advisor answered)")
    lines.append(f"  total_duration_ms: {response.total_duration_ms:.1f}")
    return "\n".join(lines)


def main() -> None:
    from app.config.logging import configure_logging

    parser = argparse.ArgumentParser(description="Ask a grounded question over the Northstar knowledge base.")
    parser.add_argument("question", nargs="?", default=None, help="Question to answer")
    parser.add_argument("--advisor", default=None, help="Advisor id to answer as (see --list-advisors)")
    parser.add_argument(
        "--auto-route", action="store_true",
        help="Automatically route to the best advisor(s) instead of manually selecting one (mutually exclusive with --advisor)",
    )
    parser.add_argument("--list-advisors", action="store_true", help="List available advisors and exit")
    parser.add_argument("--top-k", type=int, default=None, help="Override number of chunks retrieved")
    parser.add_argument("--min-score", type=float, default=None, help="Override CONTEXT_MIN_SCORE")
    parser.add_argument("--model", default=None, help="Override LLM_MODEL")
    parser.add_argument("--show-context", action="store_true", help="Print the context blocks sent to the model")
    parser.add_argument("--show-diagnostics", action="store_true", help="Print retrieval/model diagnostics")
    parser.add_argument("--show-prompts", action="store_true", help="Print the exact system/user prompts sent")
    parser.add_argument("--source-file", default=None, help="Restrict retrieval to chunks from this source_file")
    parser.add_argument("--document-id", default=None, help="Restrict retrieval to chunks from this document_id")
    args = parser.parse_args()

    # Knowledge-base content can contain characters outside a legacy
    # Windows console codepage; never crash the CLI over stdout encoding.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.list_advisors:
        print(_format_advisor_list())
        return

    if not args.question:
        parser.error("the following arguments are required: question (unless --list-advisors is given)")

    if args.advisor and args.auto_route:
        parser.error("--advisor and --auto-route are mutually exclusive")

    advisor = None
    if args.advisor:
        try:
            advisor = get_advisor(args.advisor)
        except UnknownAdvisorError as exc:
            print(f"Invalid advisor: {exc}")
            raise SystemExit(1) from None

    configure_logging()

    settings = RagSettings.from_env()
    if args.min_score is not None:
        settings = dataclasses.replace(settings, context_min_score=args.min_score)
    if args.model is not None:
        settings = dataclasses.replace(settings, llm_model=args.model)

    if args.auto_route:
        orchestrator = build_default_orchestrator(rag_settings=settings)
        try:
            response = orchestrator.ask(args.question)
        except QuestionValidationError as exc:
            print(f"Invalid question: {exc}")
            raise SystemExit(1) from None
        except ModelProviderError as exc:
            print(f"The language model is currently unavailable: {exc}")
            raise SystemExit(1) from None

        print(_format_routing(response.routing))
        print(_format_consolidated_answer(response))
        if args.show_diagnostics:
            print(_format_consolidated_diagnostics(response))
        return

    service = build_default_rag_service(rag_settings=settings)

    filters: dict[str, str] = {}
    if args.source_file:
        filters["source_file"] = args.source_file
    if args.document_id:
        filters["document_id"] = args.document_id

    on_context_built = (lambda result: print(_format_context(result))) if args.show_context else None
    on_prompt_built = (lambda prompt: print(_format_prompt(prompt))) if args.show_prompts else None

    try:
        if advisor is not None:
            answer = advisor.ask(
                service,
                args.question,
                top_k=args.top_k,
                filters=filters,
                on_context_built=on_context_built,
                on_prompt_built=on_prompt_built,
            )
        else:
            answer = service.ask(
                args.question,
                top_k=args.top_k,
                filters=filters,
                on_context_built=on_context_built,
                on_prompt_built=on_prompt_built,
            )
    except QuestionValidationError as exc:
        print(f"Invalid question: {exc}")
        raise SystemExit(1) from None
    except ModelProviderError as exc:
        print(f"The language model is currently unavailable: {exc}")
        raise SystemExit(1) from None

    if advisor is not None:
        print(f"Advisor: {advisor.display_name}\n")
    print(_format_answer(answer))
    if args.show_diagnostics:
        print(_format_diagnostics(answer))


if __name__ == "__main__":
    main()
