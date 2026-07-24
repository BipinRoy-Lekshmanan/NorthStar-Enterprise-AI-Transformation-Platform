"""CLI entry point for the grounded RAG assistant.

    python -m app.rag.ask "How should a Sev-1 incident be handled?"

Pure formatting only -- no prompt text, business logic, or citation
parsing lives here (see `app.rag.pipeline`, `app.config.prompt_config`,
`app.rag.citation_engine`). `--show-context`/`--show-prompts` are wired
via optional callback hooks on `RagService.ask()` so the debug-only
content never has to pass through (or leak into) the `RagAnswer` model.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys

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


def main() -> None:
    from app.config.logging import configure_logging

    parser = argparse.ArgumentParser(description="Ask a grounded question over the Northstar knowledge base.")
    parser.add_argument("question", help="Question to answer")
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

    configure_logging()

    settings = RagSettings.from_env()
    if args.min_score is not None:
        settings = dataclasses.replace(settings, context_min_score=args.min_score)
    if args.model is not None:
        settings = dataclasses.replace(settings, llm_model=args.model)

    service = build_default_rag_service(rag_settings=settings)

    filters: dict[str, str] = {}
    if args.source_file:
        filters["source_file"] = args.source_file
    if args.document_id:
        filters["document_id"] = args.document_id

    on_context_built = (lambda result: print(_format_context(result))) if args.show_context else None
    on_prompt_built = (lambda prompt: print(_format_prompt(prompt))) if args.show_prompts else None

    try:
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

    print(_format_answer(answer))
    if args.show_diagnostics:
        print(_format_diagnostics(answer))


if __name__ == "__main__":
    main()
