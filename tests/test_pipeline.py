import json

from app.config.settings import IngestionSettings
from app.ingestion.pipeline import IngestionPipeline


def _settings(kb_dir, out_dir) -> IngestionSettings:
    return IngestionSettings(
        knowledge_base_dirs=(kb_dir,),
        supported_extensions=(".md",),
        chunk_size=500,
        chunk_overlap=50,
        log_level="INFO",
        output_dir=out_dir,
    )


def _seed_knowledge_base(kb_dir):
    kb_dir.mkdir()
    (kb_dir / "01_Good.md").write_text(
        "---\ndocument_id: NLC-TEST-001\ntitle: Good Doc\n---\n\n"
        "# Good Doc\n\n## Section One\n\n"
        + ("Enough content to form a real chunk. " * 20)
        + "\n\n## Section Two\n\nMore content here.\n",
        encoding="utf-8",
    )
    (kb_dir / "02_NoFrontmatter.md").write_text(
        "# Plain Document\n\nJust a short body.\n", encoding="utf-8"
    )
    (kb_dir / "03_Bad.md").write_bytes(b"\xff\xfe\x00broken")
    (kb_dir / ".hidden.md").write_text("# Hidden\n\nShould be ignored.\n", encoding="utf-8")


def test_pipeline_runs_end_to_end_and_persists_artifacts(tmp_path):
    kb_dir = tmp_path / "kb"
    out_dir = tmp_path / "out"
    _seed_knowledge_base(kb_dir)

    result = IngestionPipeline(settings=_settings(kb_dir, out_dir)).run(persist=True)

    assert result.summary["documents_loaded"] == 2
    assert result.summary["documents_failed"] == 1
    assert result.summary["chunks_created"] == len(result.chunks) > 0

    chunks_file = out_dir / "chunks.jsonl"
    errors_file = out_dir / "errors.json"
    summary_file = out_dir / "summary.json"
    assert chunks_file.exists()
    assert errors_file.exists()
    assert summary_file.exists()

    persisted_chunks = [json.loads(line) for line in chunks_file.read_text(encoding="utf-8").splitlines()]
    assert len(persisted_chunks) == len(result.chunks)
    assert persisted_chunks[0]["source_path"] == "01_Good.md"
    assert persisted_chunks[0]["document_id"] == "NLC-TEST-001"

    errors = json.loads(errors_file.read_text(encoding="utf-8"))
    assert len(errors) == 1
    assert errors[0]["source_path"] == "03_Bad.md"

    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    assert summary == result.summary


def test_pipeline_can_run_without_persisting(tmp_path):
    kb_dir = tmp_path / "kb"
    out_dir = tmp_path / "out"
    _seed_knowledge_base(kb_dir)

    result = IngestionPipeline(settings=_settings(kb_dir, out_dir)).run(persist=False)

    assert result.summary["documents_loaded"] == 2
    assert not out_dir.exists()
