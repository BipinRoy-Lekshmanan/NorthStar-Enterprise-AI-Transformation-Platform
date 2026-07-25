"""Tests for OpenAIModelProvider using a fake `openai` module injected into
sys.modules -- exercises the real request-building, response-parsing,
retry, and error-translation logic without installing or calling the
real SDK. `_translate_error` matches on exception *class name* (see
app/services/openai_llm_provider.py), so these fakes only need to share
names with the real SDK's exception classes, not inherit from them.
"""

from __future__ import annotations

import sys
import types

import pytest

from app.resilience.circuit_breaker import CircuitBreaker
from app.services.llm_service import (
    ModelConfigurationError,
    ModelProviderError,
    ModelRateLimitError,
    ModelTimeoutError,
    ModelUnavailableError,
)


class AuthenticationError(Exception):
    pass


class RateLimitError(Exception):
    pass


class APITimeoutError(Exception):
    pass


class NotFoundError(Exception):
    pass


class APIConnectionError(Exception):
    pass


class _FakeUsage:
    def __init__(self, prompt_tokens, completion_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content, finish_reason="stop"):
        self.message = _FakeMessage(content)
        self.finish_reason = finish_reason


class _FakeChatCompletion:
    def __init__(self, content, model, finish_reason="stop", prompt_tokens=10, completion_tokens=5):
        self.choices = [_FakeChoice(content, finish_reason)]
        self.model = model
        self.usage = _FakeUsage(prompt_tokens, completion_tokens)


class _FakeCompletions:
    def __init__(self, behavior):
        self._behavior = behavior

    def create(self, **kwargs):
        return self._behavior(kwargs)


class _FakeChat:
    def __init__(self, behavior):
        self.completions = _FakeCompletions(behavior)


class _FakeOpenAIClient:
    def __init__(self, api_key=None, timeout=None, behavior=None):
        self.api_key = api_key
        self.chat = _FakeChat(behavior)


def _install_fake_openai_module(monkeypatch, behavior):
    fake_module = types.ModuleType("openai")
    fake_module.OpenAI = lambda api_key=None, timeout=None: _FakeOpenAIClient(api_key, timeout, behavior)
    fake_module.AuthenticationError = AuthenticationError
    fake_module.RateLimitError = RateLimitError
    fake_module.APITimeoutError = APITimeoutError
    fake_module.NotFoundError = NotFoundError
    fake_module.APIConnectionError = APIConnectionError
    monkeypatch.setitem(sys.modules, "openai", fake_module)
    return fake_module


def _make_provider(monkeypatch, behavior, **kwargs):
    _install_fake_openai_module(monkeypatch, behavior)
    from app.services.openai_llm_provider import OpenAIModelProvider

    return OpenAIModelProvider(api_key="fake-key-marker", model="gpt-4o-mini", **kwargs)


def test_missing_openai_package_raises_configuration_error(monkeypatch):
    # Setting sys.modules["openai"] = None makes `import openai` raise
    # ImportError (documented CPython behavior) -- necessary because the
    # real package may genuinely be installed in this environment, so
    # merely deleting the sys.modules entry would just reimport it fresh.
    monkeypatch.setitem(sys.modules, "openai", None)
    from app.services.openai_llm_provider import OpenAIModelProvider

    with pytest.raises(ModelConfigurationError, match="pip install openai"):
        OpenAIModelProvider(api_key="key", model="gpt-4o-mini")


def test_successful_generate_returns_model_response(monkeypatch):
    captured_kwargs = {}

    def behavior(kwargs):
        captured_kwargs.update(kwargs)
        return _FakeChatCompletion(content="Grounded answer [S1]", model="gpt-4o-mini")

    provider = _make_provider(monkeypatch, behavior)

    response = provider.generate(system_prompt="sys prompt", user_prompt="user prompt", temperature=0.0, max_tokens=256)

    assert response.text == "Grounded answer [S1]"
    assert response.provider == "openai"
    assert response.model == "gpt-4o-mini"
    assert response.input_tokens == 10
    assert response.output_tokens == 5
    assert response.finish_reason == "stop"
    assert response.latency_ms >= 0

    assert captured_kwargs["model"] == "gpt-4o-mini"
    assert captured_kwargs["temperature"] == 0.0
    assert captured_kwargs["max_tokens"] == 256
    assert captured_kwargs["messages"] == [
        {"role": "system", "content": "sys prompt"},
        {"role": "user", "content": "user prompt"},
    ]


def test_default_max_tokens_used_when_not_specified(monkeypatch):
    captured_kwargs = {}

    def behavior(kwargs):
        captured_kwargs.update(kwargs)
        return _FakeChatCompletion(content="answer", model="gpt-4o-mini")

    provider = _make_provider(monkeypatch, behavior)
    provider.generate(system_prompt="s", user_prompt="u")

    assert captured_kwargs["max_tokens"] == 1024


def test_authentication_error_translates_and_is_not_retried(monkeypatch):
    call_count = {"n": 0}

    def behavior(kwargs):
        call_count["n"] += 1
        raise AuthenticationError("bad key")

    provider = _make_provider(monkeypatch, behavior, max_retries=3)

    with pytest.raises(ModelConfigurationError, match="authentication failed"):
        provider.generate(system_prompt="s", user_prompt="u")

    assert call_count["n"] == 1  # not retryable, so no retries


def test_rate_limit_error_translates_after_exhausting_retries(monkeypatch):
    def behavior(kwargs):
        raise RateLimitError("slow down")

    provider = _make_provider(monkeypatch, behavior, max_retries=0)

    with pytest.raises(ModelRateLimitError):
        provider.generate(system_prompt="s", user_prompt="u")


def test_timeout_error_translates(monkeypatch):
    def behavior(kwargs):
        raise APITimeoutError("timed out")

    provider = _make_provider(monkeypatch, behavior, max_retries=0)

    with pytest.raises(ModelTimeoutError):
        provider.generate(system_prompt="s", user_prompt="u")


def test_not_found_error_translates_to_configuration_error(monkeypatch):
    def behavior(kwargs):
        raise NotFoundError("unknown model")

    provider = _make_provider(monkeypatch, behavior, max_retries=0)

    with pytest.raises(ModelConfigurationError, match="Unknown OpenAI model"):
        provider.generate(system_prompt="s", user_prompt="u")


def test_unexpected_error_translates_to_generic_provider_error(monkeypatch):
    def behavior(kwargs):
        raise ValueError("something odd")

    provider = _make_provider(monkeypatch, behavior, max_retries=0)

    with pytest.raises(ModelProviderError):
        provider.generate(system_prompt="s", user_prompt="u")


def test_repeated_rate_limit_failures_open_the_circuit_breaker(monkeypatch):
    def behavior(kwargs):
        raise RateLimitError("slow down")

    breaker = CircuitBreaker(name="test", failure_threshold=2)
    provider = _make_provider(monkeypatch, behavior, max_retries=0, circuit_breaker=breaker)

    for _ in range(2):
        with pytest.raises(ModelRateLimitError):
            provider.generate(system_prompt="s", user_prompt="u")

    # Breaker is now open -- the next call fails fast as ModelUnavailableError,
    # translated from CircuitBreakerOpenError, without ever calling the client.
    with pytest.raises(ModelUnavailableError):
        provider.generate(system_prompt="s", user_prompt="u")


def test_repeated_authentication_failures_do_not_open_the_circuit_breaker(monkeypatch):
    """A permanent config error (bad key) should never get masked behind
    "circuit breaker open" -- it isn't in the breaker's failure set, so
    it always propagates with its own specific, actionable type."""

    def behavior(kwargs):
        raise AuthenticationError("bad key")

    breaker = CircuitBreaker(name="test", failure_threshold=1)
    provider = _make_provider(monkeypatch, behavior, max_retries=0, circuit_breaker=breaker)

    for _ in range(5):
        with pytest.raises(ModelConfigurationError, match="authentication failed"):
            provider.generate(system_prompt="s", user_prompt="u")


def test_api_key_never_appears_in_log_output(monkeypatch, caplog):
    def behavior(kwargs):
        return _FakeChatCompletion(content="answer", model="gpt-4o-mini")

    provider = _make_provider(monkeypatch, behavior)

    with caplog.at_level("DEBUG"):
        provider.generate(system_prompt="s", user_prompt="u")

    assert "fake-key-marker" not in caplog.text
