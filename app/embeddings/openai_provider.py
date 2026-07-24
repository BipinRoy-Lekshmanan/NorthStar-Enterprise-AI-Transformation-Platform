"""OpenAI-backed `EmbeddingProvider`.

The `openai` package is imported lazily inside `__init__`, not at module
load time, so nothing outside this file needs the SDK installed (or an
API key set) unless this provider is explicitly selected via
`EMBEDDING_PROVIDER=openai`.
"""

from __future__ import annotations

import logging

from app.embeddings.vectorizer import (
    EmbeddingProviderError,
    EmbeddingProviderInfo,
    EmbeddingRateLimitError,
    EmbeddingTimeoutError,
    retry_with_backoff,
)

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_BATCH_SIZE = 100


class OpenAIEmbeddingProvider:
    """Wraps `openai.OpenAI().embeddings.create` behind the `EmbeddingProvider` interface."""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        dimensions: int = 512,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = 3,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise EmbeddingProviderError(
                "EMBEDDING_PROVIDER=openai requires the 'openai' package: pip install openai"
            ) from exc

        self._client = OpenAI(api_key=api_key, timeout=timeout)
        self._model = model
        self._dimensions = dimensions
        self._max_retries = max_retries
        self._batch_size = batch_size

    @property
    def info(self) -> EmbeddingProviderInfo:
        return EmbeddingProviderInfo(provider="openai", model=self._model, dimensions=self._dimensions)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        total_chars = sum(len(t) for t in texts)
        logger.info(
            "Embedding %d text(s), %d total chars via OpenAI model=%s", len(texts), total_chars, self._model
        )

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            vectors.extend(self._embed_batch(batch))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed_batch([text])[0]

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        def call() -> list[list[float]]:
            try:
                response = self._client.embeddings.create(
                    input=batch,
                    model=self._model,
                    dimensions=self._dimensions,
                )
            except Exception as exc:  # narrowed below by class name to avoid a hard SDK import at module scope
                raise self._translate_error(exc) from exc
            return [item.embedding for item in response.data]

        return retry_with_backoff(call, max_retries=self._max_retries)

    @staticmethod
    def _translate_error(exc: Exception) -> Exception:
        name = type(exc).__name__
        if name == "RateLimitError":
            return EmbeddingRateLimitError(str(exc))
        if name in ("APITimeoutError", "Timeout"):
            return EmbeddingTimeoutError(str(exc))
        return EmbeddingProviderError(f"OpenAI embedding call failed: {exc}")
