"""Language model provider abstraction.

Defines the `LanguageModelProvider` interface the RAG service depends on,
plus `FakeModelProvider`: a dependency-free, fully offline default used
by the CLI and the entire test suite. A real provider (see
`app.services.openai_llm_provider`) can be swapped in behind the same
interface without any other module knowing the difference.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)

_SOURCE_ID_PATTERN = re.compile(r"\[S\d+\]")


class ModelProviderError(Exception):
    """Base class for language model provider failures."""


class ModelTimeoutError(ModelProviderError):
    """Raised when a model call exceeds its timeout."""


class ModelRateLimitError(ModelProviderError):
    """Raised when a model provider reports rate limiting."""


class ModelConfigurationError(ModelProviderError):
    """Raised for missing credentials or invalid provider configuration."""


class ModelUnavailableError(ModelProviderError):
    """Raised when the provider cannot be reached (network/connection failure)."""


class InvalidModelResponseError(ModelProviderError):
    """Raised when a provider returns a response that cannot be parsed."""


@dataclass(frozen=True)
class ModelResponse:
    text: str
    provider: str
    model: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None


class LanguageModelProvider(Protocol):
    """The interface `RagService` depends on.

    No module outside `app/services/` should import a vendor SDK directly
    -- everything goes through this Protocol.
    """

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        ...


class FakeModelProvider:
    """Deterministic, offline `LanguageModelProvider` for tests and the
    no-API-key-configured default.

    Never calls a network. It cites whichever `[S#]` source markers it
    finds in the rendered user prompt (our prompt template always embeds
    them -- see `app.config.prompt_config`), so RAG-workflow tests that
    exercise citation parsing get meaningful, deterministic behavior
    without any real model call.
    """

    def __init__(self, model: str = "fake-echo-v1", canned_answer: str | None = None, max_cited_sources: int = 2):
        self._model = model
        self._canned_answer = canned_answer
        self._max_cited_sources = max_cited_sources
        self.call_count = 0

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.call_count += 1
        logger.debug(
            "FakeModelProvider.generate: prompt_chars=%d max_tokens=%s",
            len(system_prompt) + len(user_prompt), max_tokens,
        )

        if self._canned_answer is not None:
            text = self._canned_answer
        else:
            source_ids = list(dict.fromkeys(_SOURCE_ID_PATTERN.findall(user_prompt)))
            cited = " ".join(source_ids[: self._max_cited_sources])
            text = f"This is a deterministic fake response for local testing. {cited}".strip()

        return ModelResponse(
            text=text,
            provider="fake",
            model=self._model,
            latency_ms=0.0,
            input_tokens=max(1, (len(system_prompt) + len(user_prompt)) // 4),
            output_tokens=max(1, len(text) // 4),
            finish_reason="end_turn",
        )
