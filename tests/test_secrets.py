"""Tests for `app.config.secrets` (Milestone 8) -- `SecretProvider`'s
`Mapping[str, str]` conformance, `EnvSecretProvider`, `StaticSecretProvider`,
and that a `SecretProvider` can be passed as the `env=` argument to an
existing settings class's `from_env()` with zero changes there.
"""

import pytest

from app.config.secrets import EnvSecretProvider, StaticSecretProvider
from app.config.settings import RagSettings


def test_static_secret_provider_get_and_getitem():
    provider = StaticSecretProvider({"API_KEY": "secret-123"})
    assert provider["API_KEY"] == "secret-123"
    assert provider.get("API_KEY") == "secret-123"
    assert provider.get("MISSING", "fallback") == "fallback"


def test_static_secret_provider_get_secret_alias():
    provider = StaticSecretProvider({"API_KEY": "secret-123"})
    assert provider.get_secret("API_KEY") == "secret-123"
    assert provider.get_secret("MISSING", "fallback") == "fallback"
    assert provider.get_secret("MISSING") is None


def test_static_secret_provider_is_iterable_and_sized():
    provider = StaticSecretProvider({"A": "1", "B": "2"})
    assert len(provider) == 2
    assert set(provider) == {"A", "B"}
    assert dict(provider) == {"A": "1", "B": "2"}


def test_static_secret_provider_missing_key_raises_keyerror():
    provider = StaticSecretProvider({})
    with pytest.raises(KeyError):
        provider["MISSING"]


def test_static_secret_provider_is_independent_of_the_source_dict():
    source = {"A": "1"}
    provider = StaticSecretProvider(source)
    source["A"] = "mutated"
    assert provider["A"] == "1"


def test_env_secret_provider_reads_from_os_environ(monkeypatch):
    monkeypatch.setenv("MY_TEST_SECRET", "value-from-env")
    provider = EnvSecretProvider()
    assert provider["MY_TEST_SECRET"] == "value-from-env"


def test_env_secret_provider_can_wrap_an_explicit_mapping_instead_of_os_environ():
    provider = EnvSecretProvider({"KEY": "explicit-value"})
    assert provider["KEY"] == "explicit-value"


def test_env_secret_provider_snapshots_rather_than_tracking_live_changes(monkeypatch):
    monkeypatch.setenv("SNAPSHOT_TEST_KEY", "before")
    provider = EnvSecretProvider()
    monkeypatch.setenv("SNAPSHOT_TEST_KEY", "after")
    assert provider["SNAPSHOT_TEST_KEY"] == "before"


def test_a_secret_provider_can_be_passed_directly_as_a_settings_env_argument():
    """The whole point of the abstraction: any SecretProvider satisfies
    the `env: Mapping[str, str]` parameter every settings class already
    accepts -- no change to app.config.settings needed."""
    provider = StaticSecretProvider({
        "LLM_PROVIDER": "fake", "LLM_MODEL": "fake-echo-v1", "LLM_TEMPERATURE": "0.0",
    })

    settings = RagSettings.from_env(env=provider)

    assert settings.llm_provider == "fake"
    assert settings.llm_model == "fake-echo-v1"
