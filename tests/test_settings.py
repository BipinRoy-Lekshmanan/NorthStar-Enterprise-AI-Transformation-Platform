from pathlib import Path

import pytest

from app.config.settings import ConfigurationError, IngestionSettings


def _env(tmp_path: Path, **overrides) -> dict:
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    base = {
        "KNOWLEDGE_BASE_DIRS": str(kb_dir),
        "SUPPORTED_EXTENSIONS": ".md",
        "CHUNK_SIZE": "1000",
        "CHUNK_OVERLAP": "100",
        "LOG_LEVEL": "INFO",
        "INGESTION_OUTPUT_DIR": str(tmp_path / "out"),
    }
    base.update(overrides)
    return base


def test_from_env_builds_valid_settings(tmp_path):
    settings = IngestionSettings.from_env(_env(tmp_path))

    assert settings.knowledge_base_dirs[0].exists()
    assert settings.supported_extensions == (".md",)
    assert settings.chunk_size == 1000
    assert settings.chunk_overlap == 100
    assert settings.log_level == "INFO"


def test_missing_knowledge_base_dir_raises_clear_error(tmp_path):
    env = _env(tmp_path, KNOWLEDGE_BASE_DIRS=str(tmp_path / "does_not_exist"))

    with pytest.raises(ConfigurationError, match="not found"):
        IngestionSettings.from_env(env)


def test_kb_dir_that_is_a_file_raises(tmp_path):
    file_path = tmp_path / "not_a_dir.md"
    file_path.write_text("hello", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="must be directories"):
        IngestionSettings.from_env(_env(tmp_path, KNOWLEDGE_BASE_DIRS=str(file_path)))


def test_overlap_must_be_smaller_than_chunk_size(tmp_path):
    with pytest.raises(ConfigurationError, match="CHUNK_OVERLAP"):
        IngestionSettings.from_env(_env(tmp_path, CHUNK_SIZE="500", CHUNK_OVERLAP="500"))


def test_invalid_chunk_size_raises(tmp_path):
    with pytest.raises(ConfigurationError, match="integer"):
        IngestionSettings.from_env(_env(tmp_path, CHUNK_SIZE="not-a-number"))


def test_invalid_log_level_raises(tmp_path):
    with pytest.raises(ConfigurationError, match="LOG_LEVEL"):
        IngestionSettings.from_env(_env(tmp_path, LOG_LEVEL="VERBOSE"))


def test_multiple_kb_dirs_supported(tmp_path):
    second = tmp_path / "kb2"
    second.mkdir()
    env = _env(tmp_path)
    env["KNOWLEDGE_BASE_DIRS"] = f"{env['KNOWLEDGE_BASE_DIRS']},{second}"

    settings = IngestionSettings.from_env(env)

    assert len(settings.knowledge_base_dirs) == 2
