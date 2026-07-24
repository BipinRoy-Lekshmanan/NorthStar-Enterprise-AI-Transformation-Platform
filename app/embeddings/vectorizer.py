"""Embedding provider abstraction.

Defines the `EmbeddingProvider` interface the rest of the application
depends on, plus `LocalHashingEmbeddingProvider`: a dependency-free,
fully offline default implementation. It uses the classic "hashing
trick" (signed feature hashing over word tokens, L2-normalized) so
cosine similarity behaves like a lightweight bag-of-words retriever --
enough to validate retrieval quality without any API key or network
call. A real provider (e.g. OpenAI, see `app.embeddings.openai_provider`)
can be swapped in behind the same interface for production-quality
semantic similarity.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from typing import Callable, Protocol, TypeVar

logger = logging.getLogger(__name__)

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_T = TypeVar("_T")


class EmbeddingProviderError(Exception):
    """Base class for embedding provider failures."""


class EmbeddingTimeoutError(EmbeddingProviderError):
    """Raised when an embedding call exceeds its timeout."""


class EmbeddingRateLimitError(EmbeddingProviderError):
    """Raised when an embedding provider reports rate limiting."""


@dataclass(frozen=True)
class EmbeddingProviderInfo:
    provider: str
    model: str
    dimensions: int


class EmbeddingProvider(Protocol):
    """The interface the rest of the application depends on.

    No module outside `app/embeddings/` should import a vendor SDK
    directly -- everything goes through this Protocol.
    """

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts (e.g. chunks) in one batch call."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string."""
        ...

    @property
    def info(self) -> EmbeddingProviderInfo:
        ...


def retry_with_backoff(
    func: Callable[[], _T],
    *,
    max_retries: int = 3,
    base_delay_seconds: float = 0.5,
    retryable: tuple[type[Exception], ...] = (EmbeddingRateLimitError, EmbeddingTimeoutError),
) -> _T:
    """Run `func`, retrying transient failures with capped exponential backoff.

    Shared by network-backed providers (see `openai_provider.py`).
    `LocalHashingEmbeddingProvider` has no I/O failure mode and does not
    use this.
    """
    attempt = 0
    while True:
        try:
            return func()
        except retryable:
            attempt += 1
            if attempt > max_retries:
                raise
            delay = base_delay_seconds * (2 ** (attempt - 1))
            logger.warning("Embedding call failed, retrying in %.1fs (attempt %d/%d)", delay, attempt, max_retries)
            time.sleep(delay)


class LocalHashingEmbeddingProvider:
    """Deterministic, offline embedding provider using signed feature hashing.

    Same text always produces the same vector (no process-random hashing:
    tokens are hashed with sha256, not Python's built-in `hash()`), which
    matters both for reproducible tests and for a persisted vector store
    that must stay valid across process restarts.
    """

    def __init__(self, model: str = "local-hashing-v1", dimensions: int = 512):
        if dimensions <= 0:
            raise ValueError(f"dimensions must be positive, got {dimensions}")
        self._model = model
        self._dimensions = dimensions

    @property
    def info(self) -> EmbeddingProviderInfo:
        return EmbeddingProviderInfo(provider="local", model=self._model, dimensions=self._dimensions)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        total_chars = sum(len(t) for t in texts)
        logger.debug("Embedding %d text(s), %d total chars (local hashing)", len(texts), total_chars)
        return [self._embed_one(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        for token in _TOKEN_PATTERN.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:8], "big") % self._dimensions
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[index] += sign

        norm = sum(v * v for v in vector) ** 0.5
        if norm == 0.0:
            return vector
        return [v / norm for v in vector]
