"""Per-model token pricing (Milestone 8) -- USD per 1 million tokens,
input and output priced separately (cached snapshot, not a live pricing
API call). Only real, paid providers get an entry; the `fake` provider
(local, no-op, used everywhere in this repo's own tests and by default
when no API key is configured) is intentionally absent, so cost
estimation returns `None` for it rather than fabricating a number.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    input_usd_per_million: float
    output_usd_per_million: float


_PRICING: dict[tuple[str, str], ModelPricing] = {
    ("openai", "gpt-4o-mini"): ModelPricing(input_usd_per_million=0.15, output_usd_per_million=0.60),
    ("openai", "gpt-4o"): ModelPricing(input_usd_per_million=2.50, output_usd_per_million=10.00),
    ("openai", "text-embedding-3-small"): ModelPricing(input_usd_per_million=0.02, output_usd_per_million=0.0),
    ("openai", "text-embedding-3-large"): ModelPricing(input_usd_per_million=0.13, output_usd_per_million=0.0),
}


def estimate_cost_usd(
    provider: str, model: str, input_tokens: int | None, output_tokens: int | None,
) -> float | None:
    """Returns `None` when the `(provider, model)` pair has no known
    price here (the `fake` provider, or a real model not yet added to
    `_PRICING`) -- callers must treat that as "cost unknown," never as
    zero cost."""
    pricing = _PRICING.get((provider, model))
    if pricing is None:
        return None
    input_cost = (input_tokens or 0) / 1_000_000 * pricing.input_usd_per_million
    output_cost = (output_tokens or 0) / 1_000_000 * pricing.output_usd_per_million
    return input_cost + output_cost
