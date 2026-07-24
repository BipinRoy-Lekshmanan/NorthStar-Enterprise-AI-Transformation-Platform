"""OpenAI-backed `LanguageModelProvider`.

The `openai` package is imported lazily inside `__init__`, not at module
load time, so nothing outside this file needs the SDK installed (or an
API key set) unless this provider is explicitly selected via
`LLM_PROVIDER=openai`. Mirrors the lazy-import / error-translation
discipline already established in `app.embeddings.openai_provider`.
"""

from __future__ import annotations

import logging
import time

from app.embeddings.vectorizer import retry_with_backoff
from app.services.llm_service import (
    InvalidModelResponseError,
    ModelConfigurationError,
    ModelProviderError,
    ModelRateLimitError,
    ModelResponse,
    ModelTimeoutError,
    ModelUnavailableError,
)

logger = logging.getLogger(__name__)


class OpenAIModelProvider:
    """Wraps `openai.OpenAI().chat.completions.create` behind `LanguageModelProvider`."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ModelConfigurationError(
                "LLM_PROVIDER=openai requires the 'openai' package: pip install openai"
            ) from exc

        self._client = OpenAI(api_key=api_key, timeout=timeout)
        self._model = model
        self._max_retries = max_retries

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        max_tokens = max_tokens or 1024
        logger.info(
            "Calling OpenAI model=%s prompt_chars=%d max_tokens=%d temperature=%.2f",
            self._model, len(system_prompt) + len(user_prompt), max_tokens, temperature,
        )

        def call():
            try:
                return self._client.chat.completions.create(
                    model=self._model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
            except Exception as exc:
                raise self._translate_error(exc) from exc

        start = time.perf_counter()
        response = retry_with_backoff(
            call,
            max_retries=self._max_retries,
            retryable=(ModelRateLimitError, ModelTimeoutError, ModelUnavailableError),
        )
        latency_ms = (time.perf_counter() - start) * 1000

        if not response.choices:
            raise InvalidModelResponseError("OpenAI response contained no choices")

        choice = response.choices[0]
        text = choice.message.content or ""
        usage = response.usage

        return ModelResponse(
            text=text,
            provider="openai",
            model=response.model,
            latency_ms=latency_ms,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            finish_reason=choice.finish_reason,
        )

    @staticmethod
    def _translate_error(exc: Exception) -> Exception:
        name = type(exc).__name__
        if name == "AuthenticationError":
            return ModelConfigurationError(f"OpenAI authentication failed: {exc}")
        if name == "RateLimitError":
            return ModelRateLimitError(str(exc))
        if name in ("APITimeoutError", "Timeout"):
            return ModelTimeoutError(str(exc))
        if name == "NotFoundError":
            return ModelConfigurationError(f"Unknown OpenAI model or endpoint: {exc}")
        if name == "APIConnectionError":
            return ModelUnavailableError(str(exc))
        return ModelProviderError(f"OpenAI call failed: {exc}")
