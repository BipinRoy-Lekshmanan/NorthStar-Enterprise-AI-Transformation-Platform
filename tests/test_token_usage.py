"""Tests for `app.telemetry.token_usage.estimate_cost_usd` (Milestone 8)."""

from app.telemetry.token_usage import estimate_cost_usd


def test_returns_none_for_the_fake_provider():
    assert estimate_cost_usd("fake", "fake-echo-v1", 1000, 500) is None


def test_returns_none_for_an_unrecognized_real_model():
    assert estimate_cost_usd("openai", "some-future-model", 1000, 500) is None


def test_computes_cost_for_a_known_model():
    cost = estimate_cost_usd("openai", "gpt-4o-mini", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == 0.15 + 0.60


def test_handles_none_token_counts_as_zero():
    cost = estimate_cost_usd("openai", "gpt-4o-mini", input_tokens=None, output_tokens=None)
    assert cost == 0.0


def test_only_input_tokens_priced_for_embedding_models():
    cost = estimate_cost_usd("openai", "text-embedding-3-small", input_tokens=1_000_000, output_tokens=0)
    assert cost == 0.02
