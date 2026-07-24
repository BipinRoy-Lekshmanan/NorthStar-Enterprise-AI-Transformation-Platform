"""Milestone 1 ingestion pipeline: discover -> load -> extract metadata -> chunk -> persist.

Produces structured, chunked output on disk that a future embedding /
vector-store step can consume. Contains no LLM calls, embeddings, or
vector database integration.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from app.config.logging import configure_logging
from app.config.settings import IngestionSettings
from app.embeddings.chunking import MarkdownChunker
from app.ingestion.document_loader import DocumentDiscoveryService
from app.ingestion.markdown_loader import MarkdownLoader
from app.models.chunk import Chunk
from app.models.document import DocumentLoadError, LoadedDocument

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    documents: list[LoadedDocument] = field(default_factory=list)
    errors: list[DocumentLoadError] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        return {
            "files_discovered": len(self.documents) + len(self.errors),
            "documents_loaded": len(self.documents),
            "documents_failed": len(self.errors),
            "chunks_created": len(self.chunks),
        }


class IngestionPipeline:
    """Wires discovery, loading, metadata extraction, and chunking together."""

    def __init__(self, settings: IngestionSettings | None = None):
        self._settings = settings or IngestionSettings.from_env()
        self._discovery = DocumentDiscoveryService(self._settings)
        self._loader = MarkdownLoader()
        self._chunker = MarkdownChunker(
            chunk_size=self._settings.chunk_size,
            chunk_overlap=self._settings.chunk_overlap,
        )

    def run(self, persist: bool = True) -> IngestionResult:
        discovered = self._discovery.discover()
        logger.info("Discovered %d candidate file(s)", len(discovered))

        result = IngestionResult()
        for file in discovered:
            loaded = self._loader.load(file)
            if isinstance(loaded, DocumentLoadError):
                result.errors.append(loaded)
                continue
            result.documents.append(loaded)
            result.chunks.extend(self._chunker.chunk(loaded))

        logger.info("Ingestion complete: %s", result.summary)

        if persist:
            self._persist(result)

        return result

    def _persist(self, result: IngestionResult) -> None:
        output_dir = self._settings.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        chunks_path = output_dir / "chunks.jsonl"
        with chunks_path.open("w", encoding="utf-8") as fh:
            for chunk in result.chunks:
                fh.write(chunk.model_dump_json())
                fh.write("\n")

        errors_path = output_dir / "errors.json"
        errors_path.write_text(
            json.dumps([error.model_dump() for error in result.errors], indent=2),
            encoding="utf-8",
        )

        summary_path = output_dir / "summary.json"
        summary_path.write_text(json.dumps(result.summary, indent=2), encoding="utf-8")

        logger.info("Wrote ingestion artifacts to %s", output_dir)


def main() -> None:
    configure_logging()
    IngestionPipeline().run()


if __name__ == "__main__":
    main()
