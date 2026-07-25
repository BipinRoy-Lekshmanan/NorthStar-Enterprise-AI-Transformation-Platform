"""Tests for `python -m app.knowledge verify-index` (Milestone 8)."""

from app.config.settings import IngestionSettings, RetrievalSettings
from app.embeddings.indexer import Indexer, build_provider_and_store
from app.ingestion.pipeline import IngestionPipeline
from app.knowledge import cli as knowledge_cli


def _seed_kb(kb_dir):
    kb_dir.mkdir(exist_ok=True)
    (kb_dir / "doc.md").write_text(
        "---\ndocument_id: NLC-ENG-001\ntitle: Testing Strategy\n---\n\n# Testing Strategy\n\n## Coverage\n\n"
        + ("Unit and integration test coverage is required before release. " * 15),
        encoding="utf-8",
    )


def _set_env(monkeypatch, tmp_path):
    _seed_kb(tmp_path / "kb")
    monkeypatch.setenv("KNOWLEDGE_BASE_DIRS", str(tmp_path / "kb"))
    monkeypatch.setenv("INGESTION_OUTPUT_DIR", str(tmp_path / "processed"))
    monkeypatch.setenv("VECTOR_STORE_DIR", str(tmp_path / "vector_store"))
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")


def test_verify_index_exits_0_when_healthy(tmp_path, monkeypatch, capsys):
    _set_env(monkeypatch, tmp_path)
    ingestion_settings = IngestionSettings.from_env()
    retrieval_settings = RetrievalSettings.from_env()
    provider, store = build_provider_and_store(retrieval_settings)
    Indexer(provider, store).index_from_pipeline(IngestionPipeline(settings=ingestion_settings))

    exit_code = knowledge_cli.main(["verify-index"])

    assert exit_code == 0
    assert "OK" in capsys.readouterr().out


def test_verify_index_exits_1_when_never_indexed(tmp_path, monkeypatch, capsys):
    _set_env(monkeypatch, tmp_path)

    exit_code = knowledge_cli.main(["verify-index"])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "ISSUES FOUND" in output
    assert "not yet indexed" in output
