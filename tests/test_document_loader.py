from pathlib import Path

from app.config.settings import IngestionSettings
from app.ingestion.document_loader import DocumentDiscoveryService


def _settings(*kb_dirs: Path, extensions=(".md",)) -> IngestionSettings:
    return IngestionSettings(
        knowledge_base_dirs=tuple(kb_dirs),
        supported_extensions=extensions,
        chunk_size=1000,
        chunk_overlap=100,
        log_level="INFO",
        output_dir=kb_dirs[0] / "out" if kb_dirs else Path("out"),
    )


def test_discovers_markdown_files_recursively(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.md").write_text("# One", encoding="utf-8")
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "two.md").write_text("# Two", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored, wrong extension", encoding="utf-8")

    files = DocumentDiscoveryService(_settings(tmp_path)).discover()

    assert [f.relative_path for f in files] == ["a/one.md", "b/two.md"]


def test_ignores_hidden_files_and_directories(tmp_path):
    (tmp_path / ".hidden_dir").mkdir()
    (tmp_path / ".hidden_dir" / "secret.md").write_text("secret", encoding="utf-8")
    (tmp_path / ".hidden.md").write_text("secret", encoding="utf-8")
    (tmp_path / "visible.md").write_text("# Visible", encoding="utf-8")

    files = DocumentDiscoveryService(_settings(tmp_path)).discover()

    assert [f.relative_path for f in files] == ["visible.md"]


def test_ignores_generated_and_lock_files(tmp_path):
    (tmp_path / "~$locked.md").write_text("locked", encoding="utf-8")
    (tmp_path / "output.generated.md").write_text("generated", encoding="utf-8")
    (tmp_path / "real.md").write_text("# Real", encoding="utf-8")

    files = DocumentDiscoveryService(_settings(tmp_path)).discover()

    assert [f.relative_path for f in files] == ["real.md"]


def test_deterministic_order_across_runs(tmp_path):
    names = ["zeta.md", "alpha.md", "mid.md"]
    for name in names:
        (tmp_path / name).write_text(f"# {name}", encoding="utf-8")

    first = [f.relative_path for f in DocumentDiscoveryService(_settings(tmp_path)).discover()]
    second = [f.relative_path for f in DocumentDiscoveryService(_settings(tmp_path)).discover()]

    assert first == second == sorted(names)


def test_missing_directory_is_reported_and_skipped_not_raised(tmp_path, caplog):
    missing = tmp_path / "does_not_exist"

    with caplog.at_level("ERROR"):
        files = DocumentDiscoveryService(_settings(missing)).discover()

    assert files == []
    assert "not found" in caplog.text


def test_one_missing_dir_does_not_block_a_valid_one(tmp_path):
    valid = tmp_path / "valid"
    valid.mkdir()
    (valid / "doc.md").write_text("# Doc", encoding="utf-8")
    missing = tmp_path / "missing"

    files = DocumentDiscoveryService(_settings(missing, valid)).discover()

    assert [f.relative_path for f in files] == ["doc.md"]
