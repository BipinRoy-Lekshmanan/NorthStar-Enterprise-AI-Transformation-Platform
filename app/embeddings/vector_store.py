"""Local persistent vector store.

A deliberately simple, dependency-light store: an in-memory list of
L2-normalized vectors (cosine similarity via dot product) plus JSON
sidecar metadata, persisted to plain files. No ANN index -- a linear
scan is fast enough at this knowledge base's scale (hundreds to a few
thousand chunks) and keeps the implementation easy to reason about and
swap out later (e.g. for pgvector/OpenSearch/a managed vector DB) behind
the same `VectorStore` protocol.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

logger = logging.getLogger(__name__)

_EMBEDDINGS_FILENAME = "embeddings.npy"
_METADATA_FILENAME = "chunk_metadata.jsonl"
_STATE_FILENAME = "index_state.json"


class VectorStoreError(Exception):
    """Raised for invalid vector-store operations (dimension mismatch, corrupt persisted state, ...)."""


@dataclass(frozen=True)
class VectorMatch:
    chunk_id: str
    score: float
    metadata: dict[str, Any]


class VectorStore(Protocol):
    def upsert(self, chunk_ids: list[str], vectors: list[list[float]], metadata: list[dict[str, Any]]) -> None: ...
    def delete(self, chunk_ids: list[str]) -> None: ...
    def search(self, query_vector: list[float], top_k: int) -> list[VectorMatch]: ...
    def existing_ids(self) -> set[str]: ...
    def count(self) -> int: ...
    def persist(self) -> None: ...


class LocalVectorStore:
    """Numpy + JSON-backed `VectorStore`, persisted under a single directory."""

    def __init__(self, directory: Path):
        self._directory = directory
        self._chunk_ids: list[str] = []
        self._id_to_row: dict[str, int] = {}
        self._vectors: list[np.ndarray] = []
        self._metadata: dict[str, dict[str, Any]] = {}
        self._dimensions: int | None = None
        self._provider: str | None = None
        self._model: str | None = None
        self._load()

    # -- provider/model bookkeeping ---------------------------------------------------

    def set_source_info(self, provider: str, model: str) -> None:
        """Record which embedding provider/model populated this store.

        If the store already holds vectors from a *different* provider or
        model, this raises rather than silently mixing incompatible
        embeddings -- the caller should point `VECTOR_STORE_DIR` at a new
        (empty) directory to switch providers.
        """
        if self._provider is not None and (self._provider, self._model) != (provider, model):
            raise VectorStoreError(
                f"Vector store at {self._directory} was built with provider="
                f"{self._provider!r} model={self._model!r}; refusing to mix in "
                f"provider={provider!r} model={model!r}. Use a different "
                "VECTOR_STORE_DIR to switch providers."
            )
        self._provider, self._model = provider, model

    # -- mutation -----------------------------------------------------------------------

    def upsert(self, chunk_ids: list[str], vectors: list[list[float]], metadata: list[dict[str, Any]]) -> None:
        if not (len(chunk_ids) == len(vectors) == len(metadata)):
            raise VectorStoreError("chunk_ids, vectors, and metadata must be the same length")

        for chunk_id, vector, meta in zip(chunk_ids, vectors, metadata):
            array = self._to_normalized_array(vector)
            if self._dimensions is None:
                self._dimensions = array.shape[0]
            elif array.shape[0] != self._dimensions:
                raise VectorStoreError(
                    f"Embedding dimension mismatch: store expects {self._dimensions}, got {array.shape[0]} "
                    f"for chunk_id={chunk_id!r}."
                )

            self._metadata[chunk_id] = meta
            if chunk_id in self._id_to_row:
                self._vectors[self._id_to_row[chunk_id]] = array
            else:
                self._id_to_row[chunk_id] = len(self._chunk_ids)
                self._chunk_ids.append(chunk_id)
                self._vectors.append(array)

        logger.info("Upserted %d chunk(s); store now holds %d", len(chunk_ids), self.count())

    def delete(self, chunk_ids: list[str]) -> None:
        to_remove = set(chunk_ids) & set(self._id_to_row)
        if not to_remove:
            return

        kept_ids = [cid for cid in self._chunk_ids if cid not in to_remove]
        kept_vectors = [self._vectors[self._id_to_row[cid]] for cid in kept_ids]
        for cid in to_remove:
            self._metadata.pop(cid, None)

        self._chunk_ids = kept_ids
        self._vectors = kept_vectors
        self._id_to_row = {cid: i for i, cid in enumerate(kept_ids)}

        logger.info("Deleted %d chunk(s); store now holds %d", len(to_remove), self.count())

    # -- read ---------------------------------------------------------------------------

    def search(self, query_vector: list[float], top_k: int) -> list[VectorMatch]:
        if top_k <= 0 or not self._vectors:
            return []

        query = self._to_normalized_array(query_vector)
        if query.shape[0] != self._dimensions:
            raise VectorStoreError(
                f"Query vector has dimension {query.shape[0]}, store expects {self._dimensions}."
            )

        matrix = np.vstack(self._vectors)
        scores = matrix @ query

        k = min(top_k, len(scores))
        top_indices = np.argpartition(-scores, k - 1)[:k]
        top_indices = top_indices[np.argsort(-scores[top_indices])]

        return [
            VectorMatch(
                chunk_id=self._chunk_ids[i],
                score=float(scores[i]),
                metadata=self._metadata[self._chunk_ids[i]],
            )
            for i in top_indices
        ]

    def existing_ids(self) -> set[str]:
        return set(self._id_to_row)

    def count(self) -> int:
        return len(self._chunk_ids)

    # -- persistence --------------------------------------------------------------------

    def persist(self) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)

        if self._vectors:
            matrix = np.vstack(self._vectors).astype(np.float32)
        else:
            matrix = np.zeros((0, self._dimensions or 0), dtype=np.float32)
        np.save(self._directory / _EMBEDDINGS_FILENAME, matrix)

        metadata_path = self._directory / _METADATA_FILENAME
        with metadata_path.open("w", encoding="utf-8") as fh:
            for chunk_id in self._chunk_ids:
                fh.write(json.dumps({"chunk_id": chunk_id, "metadata": self._metadata[chunk_id]}))
                fh.write("\n")

        state = {
            "provider": self._provider,
            "model": self._model,
            "dimensions": self._dimensions,
            "count": self.count(),
        }
        (self._directory / _STATE_FILENAME).write_text(json.dumps(state, indent=2), encoding="utf-8")

        logger.info("Persisted vector store (%d chunks) to %s", self.count(), self._directory)

    def _load(self) -> None:
        state_path = self._directory / _STATE_FILENAME
        embeddings_path = self._directory / _EMBEDDINGS_FILENAME
        metadata_path = self._directory / _METADATA_FILENAME

        if not state_path.exists() and not embeddings_path.exists() and not metadata_path.exists():
            return  # fresh, empty store -- not an error

        if not (state_path.exists() and embeddings_path.exists() and metadata_path.exists()):
            raise VectorStoreError(
                f"Vector store at {self._directory} is incomplete (expected all of "
                f"{_STATE_FILENAME}, {_EMBEDDINGS_FILENAME}, {_METADATA_FILENAME})."
            )

        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            matrix = np.load(embeddings_path)
            lines = metadata_path.read_text(encoding="utf-8").splitlines()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise VectorStoreError(f"Failed to load vector store at {self._directory}: {exc}") from exc

        if matrix.shape[0] != len(lines):
            raise VectorStoreError(
                f"Vector store at {self._directory} is inconsistent: "
                f"{matrix.shape[0]} embeddings but {len(lines)} metadata records."
            )

        chunk_ids: list[str] = []
        metadata: dict[str, dict[str, Any]] = {}
        for line in lines:
            record = json.loads(line)
            chunk_ids.append(record["chunk_id"])
            metadata[record["chunk_id"]] = record["metadata"]

        self._chunk_ids = chunk_ids
        self._id_to_row = {cid: i for i, cid in enumerate(chunk_ids)}
        self._vectors = [matrix[i] for i in range(matrix.shape[0])]
        self._metadata = metadata
        self._dimensions = state.get("dimensions") or (matrix.shape[1] if matrix.ndim == 2 else None)
        self._provider = state.get("provider")
        self._model = state.get("model")

        logger.info("Loaded vector store (%d chunks) from %s", self.count(), self._directory)

    @staticmethod
    def _to_normalized_array(vector: list[float]) -> np.ndarray:
        array = np.asarray(vector, dtype=np.float32)
        norm = np.linalg.norm(array)
        if norm == 0.0:
            return array
        return array / norm
