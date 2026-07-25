"""Tests for `OpenAIEmbeddingProvider` using a fake `openai` module
injected into sys.modules -- same technique as
`test_openai_llm_provider.py`. Written for Milestone 8 to close a
pre-existing gap: this provider had zero test coverage anywhere in the
suite before this file, discovered while wiring in retry/circuit-breaker
resilience and confirmed by grepping for its class name across tests/.
"""

from __future__ import annotations

import sys
import types

import pytest

from app.embeddings.vectorizer import EmbeddingProviderError, EmbeddingRateLimitError, EmbeddingTimeoutError
from app.resilience.circuit_breaker import CircuitBreaker


class RateLimitError(Exception):
    pass


class APITimeoutError(Exception):
    pass


class AuthenticationError(Exception):
    pass


class _FakeEmbeddingItem:
    def __init__(self, embedding):
        self.embedding = embedding


class _FakeEmbeddingResponse:
    def __init__(self, vectors):
        self.data = [_FakeEmbeddingItem(v) for v in vectors]


class _FakeEmbeddings:
    def __init__(self, behavior):
        self._behavior = behavior

    def create(self, **kwargs):
        return self._behavior(kwargs)


class _FakeOpenAIClient:
    def __init__(self, api_key=None, timeout=None, behavior=None):
        self.api_key = api_key
        self.embeddings = _FakeEmbeddings(behavior)


def _install_fake_openai_module(monkeypatch, behavior):
    fake_module = types.ModuleType("openai")
    fake_module.OpenAI = lambda api_key=None, timeout=None: _FakeOpenAIClient(api_key, timeout, behavior)
    fake_module.RateLimitError = RateLimitError
    fake_module.APITimeoutError = APITimeoutError
    fake_module.AuthenticationError = AuthenticationError
    monkeypatch.setitem(sys.modules, "openai", fake_module)
    return fake_module


def _make_provider(monkeypatch, behavior, **kwargs):
    _install_fake_openai_module(monkeypatch, behavior)
    from app.embeddings.openai_provider import OpenAIEmbeddingProvider

    return OpenAIEmbeddingProvider(api_key="fake-key-marker", model="text-embedding-3-small", dimensions=8, **kwargs)


def test_missing_openai_package_raises_provider_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", None)
    from app.embeddings.openai_provider import OpenAIEmbeddingProvider

    with pytest.raises(EmbeddingProviderError, match="pip install openai"):
        OpenAIEmbeddingProvider(api_key="key")


def test_embed_query_returns_a_single_vector(monkeypatch):
    def behavior(kwargs):
        return _FakeEmbeddingResponse([[0.1] * 8])

    provider = _make_provider(monkeypatch, behavior)
    vector = provider.embed_query("hello world")
    assert vector == [0.1] * 8


def test_embed_texts_batches_requests(monkeypatch):
    captured_batches = []

    def behavior(kwargs):
        captured_batches.append(kwargs["input"])
        return _FakeEmbeddingResponse([[0.0] * 8 for _ in kwargs["input"]])

    provider = _make_provider(monkeypatch, behavior, batch_size=2)
    vectors = provider.embed_texts(["a", "b", "c"])

    assert len(vectors) == 3
    assert captured_batches == [["a", "b"], ["c"]]


def test_embed_texts_empty_list_short_circuits_without_a_call(monkeypatch):
    def behavior(kwargs):
        raise AssertionError("should never be called for an empty input list")

    provider = _make_provider(monkeypatch, behavior)
    assert provider.embed_texts([]) == []


def test_rate_limit_error_translates_after_exhausting_retries(monkeypatch):
    def behavior(kwargs):
        raise RateLimitError("slow down")

    provider = _make_provider(monkeypatch, behavior, max_retries=0)
    with pytest.raises(EmbeddingRateLimitError):
        provider.embed_query("hello")


def test_timeout_error_translates(monkeypatch):
    def behavior(kwargs):
        raise APITimeoutError("timed out")

    provider = _make_provider(monkeypatch, behavior, max_retries=0)
    with pytest.raises(EmbeddingTimeoutError):
        provider.embed_query("hello")


def test_authentication_error_translates_to_generic_provider_error_and_is_not_retried(monkeypatch):
    call_count = {"n": 0}

    def behavior(kwargs):
        call_count["n"] += 1
        raise AuthenticationError("bad key")

    provider = _make_provider(monkeypatch, behavior, max_retries=3)
    with pytest.raises(EmbeddingProviderError):
        provider.embed_query("hello")
    assert call_count["n"] == 1  # not one of the two retryable types, so no retries


def test_repeated_rate_limit_failures_open_the_circuit_breaker(monkeypatch):
    def behavior(kwargs):
        raise RateLimitError("slow down")

    breaker = CircuitBreaker(name="test-embedding", failure_threshold=2)
    provider = _make_provider(monkeypatch, behavior, max_retries=0, circuit_breaker=breaker)

    for _ in range(2):
        with pytest.raises(EmbeddingRateLimitError):
            provider.embed_query("hello")

    with pytest.raises(EmbeddingProviderError):
        provider.embed_query("hello")


def test_repeated_authentication_failures_do_not_open_the_circuit_breaker(monkeypatch):
    def behavior(kwargs):
        raise AuthenticationError("bad key")

    breaker = CircuitBreaker(name="test-embedding", failure_threshold=1)
    provider = _make_provider(monkeypatch, behavior, max_retries=0, circuit_breaker=breaker)

    for _ in range(5):
        with pytest.raises(EmbeddingProviderError):
            provider.embed_query("hello")


def test_api_key_never_appears_in_log_output(monkeypatch, caplog):
    def behavior(kwargs):
        return _FakeEmbeddingResponse([[0.0] * 8])

    provider = _make_provider(monkeypatch, behavior)
    with caplog.at_level("DEBUG"):
        provider.embed_query("hello")
    assert "fake-key-marker" not in caplog.text
