import pytest

from app.embeddings.vector_store import LocalVectorStore, VectorStoreError


def test_upsert_and_search_returns_most_similar_first(tmp_path):
    store = LocalVectorStore(tmp_path / "store")
    store.upsert(
        chunk_ids=["a", "b", "c"],
        vectors=[[1.0, 0.0], [0.0, 1.0], [0.9, 0.1]],
        metadata=[{"text": "a"}, {"text": "b"}, {"text": "c"}],
    )

    matches = store.search([1.0, 0.0], top_k=2)

    assert [m.chunk_id for m in matches] == ["a", "c"]
    assert matches[0].score > matches[1].score


def test_existing_ids_and_count(tmp_path):
    store = LocalVectorStore(tmp_path / "store")
    store.upsert(["a", "b"], [[1.0, 0.0], [0.0, 1.0]], [{}, {}])

    assert store.existing_ids() == {"a", "b"}
    assert store.count() == 2


def test_delete_removes_chunks(tmp_path):
    store = LocalVectorStore(tmp_path / "store")
    store.upsert(["a", "b"], [[1.0, 0.0], [0.0, 1.0]], [{}, {}])

    store.delete(["a"])

    assert store.existing_ids() == {"b"}
    assert store.count() == 1


def test_delete_of_unknown_id_is_a_no_op(tmp_path):
    store = LocalVectorStore(tmp_path / "store")
    store.upsert(["a"], [[1.0, 0.0]], [{}])

    store.delete(["does-not-exist"])

    assert store.count() == 1


def test_upsert_replaces_existing_id(tmp_path):
    store = LocalVectorStore(tmp_path / "store")
    store.upsert(["a"], [[1.0, 0.0]], [{"v": 1}])

    store.upsert(["a"], [[0.0, 1.0]], [{"v": 2}])

    assert store.count() == 1
    matches = store.search([0.0, 1.0], top_k=1)
    assert matches[0].metadata == {"v": 2}


def test_dimension_mismatch_raises(tmp_path):
    store = LocalVectorStore(tmp_path / "store")
    store.upsert(["a"], [[1.0, 0.0]], [{}])

    with pytest.raises(VectorStoreError, match="dimension"):
        store.upsert(["b"], [[1.0, 0.0, 0.0]], [{}])


def test_persist_and_reload_round_trip(tmp_path):
    directory = tmp_path / "store"
    store = LocalVectorStore(directory)
    store.set_source_info("local", "test-model")
    store.upsert(["a", "b"], [[1.0, 0.0], [0.0, 1.0]], [{"n": "a"}, {"n": "b"}])
    store.persist()

    reloaded = LocalVectorStore(directory)

    assert reloaded.count() == 2
    assert reloaded.existing_ids() == {"a", "b"}
    matches = reloaded.search([1.0, 0.0], top_k=1)
    assert matches[0].chunk_id == "a"
    assert matches[0].metadata == {"n": "a"}


def test_source_info_conflict_raises(tmp_path):
    store = LocalVectorStore(tmp_path / "store")
    store.set_source_info("local", "model-a")

    with pytest.raises(VectorStoreError, match="provider"):
        store.set_source_info("openai", "model-b")


def test_source_info_same_value_is_idempotent(tmp_path):
    store = LocalVectorStore(tmp_path / "store")
    store.set_source_info("local", "model-a")
    store.set_source_info("local", "model-a")  # should not raise


def test_search_on_empty_store_returns_empty(tmp_path):
    store = LocalVectorStore(tmp_path / "store")

    assert store.search([1.0, 0.0], top_k=5) == []


def test_search_with_top_k_zero_returns_empty(tmp_path):
    store = LocalVectorStore(tmp_path / "store")
    store.upsert(["a"], [[1.0, 0.0]], [{}])

    assert store.search([1.0, 0.0], top_k=0) == []


def test_incomplete_persisted_store_raises(tmp_path):
    directory = tmp_path / "store"
    directory.mkdir()
    (directory / "index_state.json").write_text("{}", encoding="utf-8")

    with pytest.raises(VectorStoreError):
        LocalVectorStore(directory)


def test_fresh_empty_directory_is_not_an_error(tmp_path):
    store = LocalVectorStore(tmp_path / "brand_new_store")

    assert store.count() == 0
    assert store.existing_ids() == set()
