"""Tests for `app.config.settings.CostSettings` (Milestone 8)."""

import pytest

from app.config.settings import ConfigurationError, CostSettings


def test_defaults_to_no_budget():
    settings = CostSettings.from_env(env={})
    assert settings.daily_budget_usd is None
    assert settings.budget_warning_ratio == 0.8


def test_parses_a_configured_budget():
    settings = CostSettings.from_env(env={"DAILY_BUDGET_USD": "25.50"})
    assert settings.daily_budget_usd == 25.50


def test_parses_a_custom_warning_ratio():
    settings = CostSettings.from_env(env={"BUDGET_WARNING_RATIO": "0.9"})
    assert settings.budget_warning_ratio == 0.9


def test_invalid_budget_value_raises():
    with pytest.raises(ConfigurationError, match="DAILY_BUDGET_USD"):
        CostSettings.from_env(env={"DAILY_BUDGET_USD": "not-a-number"})


def test_zero_budget_raises():
    with pytest.raises(ConfigurationError, match="positive"):
        CostSettings.from_env(env={"DAILY_BUDGET_USD": "0"})


def test_negative_budget_raises():
    with pytest.raises(ConfigurationError, match="positive"):
        CostSettings.from_env(env={"DAILY_BUDGET_USD": "-5"})


def test_warning_ratio_out_of_range_raises():
    with pytest.raises(ConfigurationError, match="BUDGET_WARNING_RATIO"):
        CostSettings.from_env(env={"BUDGET_WARNING_RATIO": "1.5"})
    with pytest.raises(ConfigurationError, match="BUDGET_WARNING_RATIO"):
        CostSettings.from_env(env={"BUDGET_WARNING_RATIO": "0"})
