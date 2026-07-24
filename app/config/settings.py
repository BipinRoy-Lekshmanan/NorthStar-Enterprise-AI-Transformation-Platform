"""Centralized configuration for the knowledge ingestion pipeline.

All values are sourced from environment variables (optionally loaded from a
``.env`` file via python-dotenv) with sane defaults for local development.
See ``.env.example`` at the project root for the full list of variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv

# app/config/settings.py -> app/config -> app -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_KNOWLEDGE_BASE_DIRS = "enterprise_knowledge_base"
DEFAULT_SUPPORTED_EXTENSIONS = ".md"
DEFAULT_CHUNK_SIZE = 1500
DEFAULT_CHUNK_OVERLAP = 200
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_OUTPUT_DIR = "data/processed"

DEFAULT_EMBEDDING_PROVIDER = "local"
DEFAULT_LOCAL_EMBEDDING_MODEL = "local-hashing-v1"
DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSIONS = 512
DEFAULT_VECTOR_STORE_DIR = "vector_store"
DEFAULT_RETRIEVAL_TOP_K = 5

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
VALID_EMBEDDING_PROVIDERS = {"local", "openai"}


class ConfigurationError(ValueError):
    """Raised when ingestion configuration is missing or invalid."""


def _resolve(path_str: str) -> Path:
    path = Path(path_str.strip())
    return path if path.is_absolute() else (PROJECT_ROOT / path)


def _split_csv(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class IngestionSettings:
    """Validated configuration for a single ingestion run."""

    knowledge_base_dirs: tuple[Path, ...]
    supported_extensions: tuple[str, ...]
    chunk_size: int
    chunk_overlap: int
    log_level: str
    output_dir: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "IngestionSettings":
        """Build settings from environment variables and validate them eagerly."""
        env = env if env is not None else os.environ

        raw_dirs = env.get("KNOWLEDGE_BASE_DIRS", DEFAULT_KNOWLEDGE_BASE_DIRS)
        knowledge_base_dirs = tuple(_resolve(p) for p in _split_csv(raw_dirs))

        raw_extensions = env.get("SUPPORTED_EXTENSIONS", DEFAULT_SUPPORTED_EXTENSIONS)
        supported_extensions = tuple(
            ext.lower() if ext.startswith(".") else f".{ext.lower()}"
            for ext in _split_csv(raw_extensions)
        )

        chunk_size = _parse_int(env, "CHUNK_SIZE", DEFAULT_CHUNK_SIZE)
        chunk_overlap = _parse_int(env, "CHUNK_OVERLAP", DEFAULT_CHUNK_OVERLAP)

        log_level = env.get("LOG_LEVEL", DEFAULT_LOG_LEVEL).strip().upper()

        output_dir = _resolve(env.get("INGESTION_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))

        settings = cls(
            knowledge_base_dirs=knowledge_base_dirs,
            supported_extensions=supported_extensions,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            log_level=log_level,
            output_dir=output_dir,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """Fail fast with a clear message when configuration cannot support ingestion."""
        if not self.knowledge_base_dirs:
            raise ConfigurationError(
                "KNOWLEDGE_BASE_DIRS must list at least one directory to scan."
            )

        missing = [str(d) for d in self.knowledge_base_dirs if not d.exists()]
        if missing:
            raise ConfigurationError(
                "Knowledge base directory(ies) not found: "
                f"{', '.join(missing)}. Check KNOWLEDGE_BASE_DIRS."
            )

        not_dirs = [str(d) for d in self.knowledge_base_dirs if not d.is_dir()]
        if not_dirs:
            raise ConfigurationError(
                "KNOWLEDGE_BASE_DIRS entries must be directories, got file(s): "
                f"{', '.join(not_dirs)}."
            )

        if not self.supported_extensions:
            raise ConfigurationError(
                "SUPPORTED_EXTENSIONS must list at least one file extension."
            )

        if self.chunk_size <= 0:
            raise ConfigurationError(
                f"CHUNK_SIZE must be a positive integer, got {self.chunk_size}."
            )

        if self.chunk_overlap < 0:
            raise ConfigurationError(
                f"CHUNK_OVERLAP must be zero or positive, got {self.chunk_overlap}."
            )

        if self.chunk_overlap >= self.chunk_size:
            raise ConfigurationError(
                f"CHUNK_OVERLAP ({self.chunk_overlap}) must be smaller than "
                f"CHUNK_SIZE ({self.chunk_size})."
            )

        if self.log_level not in VALID_LOG_LEVELS:
            raise ConfigurationError(
                f"LOG_LEVEL must be one of {sorted(VALID_LOG_LEVELS)}, got "
                f"'{self.log_level}'."
            )


@dataclass(frozen=True)
class RetrievalSettings:
    """Validated configuration for embedding + vector-store/retrieval."""

    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    vector_store_dir: Path
    retrieval_top_k: int
    openai_api_key: str | None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "RetrievalSettings":
        """Build settings from environment variables and validate them eagerly."""
        env = env if env is not None else os.environ

        embedding_provider = env.get("EMBEDDING_PROVIDER", DEFAULT_EMBEDDING_PROVIDER).strip().lower()

        default_model = (
            DEFAULT_OPENAI_EMBEDDING_MODEL
            if embedding_provider == "openai"
            else DEFAULT_LOCAL_EMBEDDING_MODEL
        )
        embedding_model = env.get("EMBEDDING_MODEL", default_model)

        embedding_dimensions = _parse_int(env, "EMBEDDING_DIMENSIONS", DEFAULT_EMBEDDING_DIMENSIONS)
        vector_store_dir = _resolve(env.get("VECTOR_STORE_DIR", DEFAULT_VECTOR_STORE_DIR))
        retrieval_top_k = _parse_int(env, "RETRIEVAL_TOP_K", DEFAULT_RETRIEVAL_TOP_K)
        openai_api_key = env.get("OPENAI_API_KEY") or None

        settings = cls(
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
            vector_store_dir=vector_store_dir,
            retrieval_top_k=retrieval_top_k,
            openai_api_key=openai_api_key,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """Fail fast with a clear message when configuration cannot support retrieval."""
        if self.embedding_provider not in VALID_EMBEDDING_PROVIDERS:
            raise ConfigurationError(
                f"EMBEDDING_PROVIDER must be one of {sorted(VALID_EMBEDDING_PROVIDERS)}, "
                f"got '{self.embedding_provider}'."
            )

        if not self.embedding_model.strip():
            raise ConfigurationError("EMBEDDING_MODEL must not be empty.")

        if self.embedding_dimensions <= 0:
            raise ConfigurationError(
                f"EMBEDDING_DIMENSIONS must be a positive integer, got {self.embedding_dimensions}."
            )

        if self.retrieval_top_k <= 0:
            raise ConfigurationError(
                f"RETRIEVAL_TOP_K must be a positive integer, got {self.retrieval_top_k}."
            )

        if self.embedding_provider == "openai" and not self.openai_api_key:
            raise ConfigurationError(
                "EMBEDDING_PROVIDER is 'openai' but OPENAI_API_KEY is not set."
            )


def _parse_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{key} must be an integer, got '{raw}'.") from exc
