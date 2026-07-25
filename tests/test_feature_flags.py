"""Tests for `app.config.feature_flags.FeatureFlagSettings` (Milestone 8)."""

import pytest

from app.config.feature_flags import FeatureFlagSettings
from app.config.settings import ConfigurationError


def test_defaults_to_no_flags_set():
    settings = FeatureFlagSettings.from_env(env={})
    assert settings.flags == {}


def test_parses_a_single_flag():
    settings = FeatureFlagSettings.from_env(env={"FEATURE_FLAGS": "background_operations=false"})
    assert settings.flags == {"background_operations": False}


def test_parses_multiple_flags():
    settings = FeatureFlagSettings.from_env(env={"FEATURE_FLAGS": "a=true, b=false, c=1"})
    assert settings.flags == {"a": True, "b": False, "c": True}


def test_is_enabled_uses_the_explicit_value_when_set():
    settings = FeatureFlagSettings.from_env(env={"FEATURE_FLAGS": "a=false"})
    assert settings.is_enabled("a", default=True) is False


def test_is_enabled_falls_back_to_default_when_unset():
    settings = FeatureFlagSettings.from_env(env={})
    assert settings.is_enabled("unset_flag", default=True) is True
    assert settings.is_enabled("unset_flag", default=False) is False


def test_entry_missing_equals_sign_raises():
    with pytest.raises(ConfigurationError, match="name=true"):
        FeatureFlagSettings.from_env(env={"FEATURE_FLAGS": "just_a_name"})


def test_entry_missing_value_raises():
    with pytest.raises(ConfigurationError, match="missing a boolean value"):
        FeatureFlagSettings.from_env(env={"FEATURE_FLAGS": "a="})


def test_entry_with_unrecognized_boolean_raises():
    with pytest.raises(ConfigurationError, match="a"):
        FeatureFlagSettings.from_env(env={"FEATURE_FLAGS": "a=maybe"})


def test_empty_entries_between_commas_are_skipped():
    settings = FeatureFlagSettings.from_env(env={"FEATURE_FLAGS": "a=true,,b=false"})
    assert settings.flags == {"a": True, "b": False}
