from app.services.llm_service import (
    FakeModelProvider,
    ModelConfigurationError,
    ModelProviderError,
    ModelRateLimitError,
    ModelResponse,
    ModelTimeoutError,
    ModelUnavailableError,
)


def test_error_hierarchy():
    assert issubclass(ModelTimeoutError, ModelProviderError)
    assert issubclass(ModelRateLimitError, ModelProviderError)
    assert issubclass(ModelConfigurationError, ModelProviderError)
    assert issubclass(ModelUnavailableError, ModelProviderError)


def test_fake_provider_returns_model_response():
    provider = FakeModelProvider()

    response = provider.generate(system_prompt="sys", user_prompt="What is [S1]?", temperature=0.0, max_tokens=100)

    assert isinstance(response, ModelResponse)
    assert response.provider == "fake"
    assert response.model == "fake-echo-v1"
    assert response.finish_reason == "end_turn"
    assert response.input_tokens is not None
    assert response.output_tokens is not None


def test_fake_provider_cites_source_markers_found_in_prompt():
    provider = FakeModelProvider()

    response = provider.generate(
        system_prompt="sys",
        user_prompt="Context [S1] ... [S2] ... [S3] ...\nQuestion: what?",
    )

    assert "[S1]" in response.text
    assert "[S2]" in response.text
    assert "[S3]" not in response.text  # max_cited_sources default is 2


def test_fake_provider_with_no_source_markers_cites_nothing():
    provider = FakeModelProvider()

    response = provider.generate(system_prompt="sys", user_prompt="no markers here")

    assert "[S" not in response.text


def test_fake_provider_canned_answer_override():
    provider = FakeModelProvider(canned_answer="Exact test answer.")

    response = provider.generate(system_prompt="sys", user_prompt="[S1] anything")

    assert response.text == "Exact test answer."


def test_fake_provider_tracks_call_count():
    provider = FakeModelProvider()
    assert provider.call_count == 0

    provider.generate(system_prompt="a", user_prompt="b")
    provider.generate(system_prompt="a", user_prompt="b")

    assert provider.call_count == 2


def test_fake_provider_is_deterministic():
    provider = FakeModelProvider()

    first = provider.generate(system_prompt="sys", user_prompt="Context [S1]\nQuestion: x")
    second = provider.generate(system_prompt="sys", user_prompt="Context [S1]\nQuestion: x")

    assert first.text == second.text
