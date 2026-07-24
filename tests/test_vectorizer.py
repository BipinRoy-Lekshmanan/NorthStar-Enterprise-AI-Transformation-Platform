from app.embeddings.vectorizer import LocalHashingEmbeddingProvider


def test_same_text_produces_same_vector():
    provider = LocalHashingEmbeddingProvider(dimensions=64)

    assert provider.embed_query("incident severity levels") == provider.embed_query("incident severity levels")


def test_deterministic_across_provider_instances():
    a = LocalHashingEmbeddingProvider(dimensions=64).embed_query("hello world")
    b = LocalHashingEmbeddingProvider(dimensions=64).embed_query("hello world")

    assert a == b


def test_vector_dimension_matches_config():
    provider = LocalHashingEmbeddingProvider(dimensions=128)

    vector = provider.embed_query("some text")

    assert len(vector) == 128
    assert provider.info.dimensions == 128


def test_vector_is_l2_normalized():
    provider = LocalHashingEmbeddingProvider(dimensions=64)

    vector = provider.embed_query("a reasonably long piece of text with many different words in it")
    norm = sum(v * v for v in vector) ** 0.5

    assert abs(norm - 1.0) < 1e-6


def test_embed_texts_matches_embed_query_elementwise():
    provider = LocalHashingEmbeddingProvider(dimensions=64)
    texts = ["alpha beta", "gamma delta"]

    assert provider.embed_texts(texts) == [provider.embed_query(t) for t in texts]


def test_similar_texts_more_similar_than_unrelated():
    provider = LocalHashingEmbeddingProvider(dimensions=256)
    a = provider.embed_query("incident severity levels sev1 sev2 outage response")
    b = provider.embed_query("incident severity classification outage response levels")
    c = provider.embed_query("quarterly revenue forecast lending business model")

    def cosine(x, y):
        return sum(xi * yi for xi, yi in zip(x, y))

    assert cosine(a, b) > cosine(a, c)


def test_provider_info():
    provider = LocalHashingEmbeddingProvider(model="test-model", dimensions=32)

    info = provider.info

    assert info.provider == "local"
    assert info.model == "test-model"
    assert info.dimensions == 32


def test_empty_text_returns_zero_vector_without_error():
    provider = LocalHashingEmbeddingProvider(dimensions=16)

    assert provider.embed_query("") == [0.0] * 16


def test_invalid_dimensions_rejected():
    import pytest

    with pytest.raises(ValueError):
        LocalHashingEmbeddingProvider(dimensions=0)
