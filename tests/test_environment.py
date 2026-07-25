"""Tests for `app.config.environment` (Milestone 8)."""

import pytest

from app.config.environment import Environment, current_environment
from app.config.settings import ConfigurationError


def test_default_environment_is_local():
    assert current_environment(env={}) == Environment.LOCAL


@pytest.mark.parametrize("value", ["local", "development", "test", "staging", "production"])
def test_every_valid_value_parses(value):
    assert current_environment(env={"APP_ENVIRONMENT": value}) == Environment(value)


def test_case_insensitive():
    assert current_environment(env={"APP_ENVIRONMENT": "PRODUCTION"}) == Environment.PRODUCTION


def test_invalid_value_raises_clear_error():
    with pytest.raises(ConfigurationError, match="APP_ENVIRONMENT"):
        current_environment(env={"APP_ENVIRONMENT": "bogus"})


def test_is_production_like():
    assert Environment.PRODUCTION.is_production_like is True
    assert Environment.STAGING.is_production_like is True
    assert Environment.LOCAL.is_production_like is False
    assert Environment.DEVELOPMENT.is_production_like is False
    assert Environment.TEST.is_production_like is False
