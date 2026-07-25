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
)
from app.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from app.resilience.concurrency import BoundedConcurrency
from app.resilience.retry import retry_with_backoff
from app.telemetry.metrics import provider_failures_total

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_BATCH_SIZE = 100
_PROVIDER_NAME = "openai_embedding"
_RETRYABLE_ERRORS = (EmbeddingRateLimitError, EmbeddingTimeoutError)


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
        circuit_breaker: CircuitBreaker | None = None,
        max_concurrent_requests: int = 5,
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
        self._circuit_breaker = circuit_breaker or CircuitBreaker(name=_PROVIDER_NAME)
        # Caps concurrent in-flight batches -- a burst of concurrent
        # embed_texts()/embed_query() calls queues rather than overwhelming
        # the provider's own connection pool or rate limits.
        self._concurrency = BoundedConcurrency(max_concurrent_requests)

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

        def call_with_retry() -> list[list[float]]:
            return retry_with_backoff(
                call, max_retries=self._max_retries, retryable=_RETRYABLE_ERRORS, provider=_PROVIDER_NAME,
            )

        try:
            with self._concurrency.acquire():
                return self._circuit_breaker.call(call_with_retry, failure_exceptions=_RETRYABLE_ERRORS)
        except CircuitBreakerOpenError as exc:
            provider_failures_total.labels(provider=_PROVIDER_NAME, error_type="CircuitBreakerOpen").inc()
            raise EmbeddingProviderError(str(exc)) from exc
        except EmbeddingProviderError as exc:
            provider_failures_total.labels(provider=_PROVIDER_NAME, error_type=type(exc).__name__).inc()
            raise

    @staticmethod
    def _translate_error(exc: Exception) -> Exception:
        name = type(exc).__name__
        if name == "RateLimitError":
            return EmbeddingRateLimitError(str(exc))
        if name in ("APITimeoutError", "Timeout"):
            return EmbeddingTimeoutError(str(exc))
        return EmbeddingProviderError(f"OpenAI embedding call failed: {exc}")
