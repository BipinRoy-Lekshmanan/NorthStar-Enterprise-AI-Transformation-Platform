from app.embeddings.indexer import Indexer
from app.embeddings.vector_store import LocalVectorStore
from app.embeddings.vectorizer import LocalHashingEmbeddingProvider
from app.models.chunk import Chunk
from app.models.query import RetrievalQuery
from app.rag.retriever import Retriever


def _chunk(chunk_id: str, text: str, **overrides) -> Chunk:
    fields = dict(
        chunk_id=chunk_id,
        text=text,
        chunk_index=0,
        source_file="doc.md",
        source_path="doc.md",
        content_hash="hash",
        char_count=len(text),
    )
    fields.update(overrides)
    return Chunk(**fields)


def _build_retriever(tmp_path, chunks, dimensions=256):
    provider = LocalHashingEmbeddingProvider(dimensions=dimensions)
    store = LocalVectorStore(tmp_path / "store")
    Indexer(provider, store).sync(chunks)
    return Retriever(provider, store)


def test_retrieve_returns_most_relevant_chunk_first(tmp_path):
    chunks = [
        _chunk(
            "incident",
            "Sev1 incidents require immediate response and executive notification.",
            source_path="16_Incident_Management.md",
        ),
        _chunk(
            "lending",
            "The lending business model covers consumer and small business loans.",
            source_path="05_Lending_Business_Model.md",
        ),
        _chunk(
            "testing",
            "Unit tests and integration tests validate software quality before release.",
            source_path="14_Testing_Strategy.md",
        ),
    ]
    retriever = _build_retriever(tmp_path, chunks)

    response = retriever.retrieve(
        RetrievalQuery(text="What is the response time for a Sev1 incident?", top_k=2)
    )

    assert response.results[0].chunk.chunk_id == "incident"
    assert response.results[0].chunk.source_path == "16_Incident_Management.md"
    assert response.results[0].rank == 1


def test_diagnostics_are_populated(tmp_path):
    retriever = _build_retriever(tmp_path, [_chunk("a", "hello world")])

    response = retriever.retrieve(RetrievalQuery(text="hello", top_k=5))

    diag = response.diagnostics
    assert diag.embedding_provider == "local"
    assert diag.total_indexed_chunks == 1
    assert diag.top_k == 5
    assert diag.embed_latency_ms >= 0
    assert diag.search_latency_ms >= 0
    assert diag.query_text == "hello"


def test_top_k_limits_results(tmp_path):
    chunks = [_chunk(str(i), f"chunk number {i} about incidents") for i in range(10)]
    retriever = _build_retriever(tmp_path, chunks)

    response = retriever.retrieve(RetrievalQuery(text="incidents", top_k=3))

    assert len(response.results) == 3
    assert [r.rank for r in response.results] == [1, 2, 3]


def test_filters_restrict_results(tmp_path):
    chunks = [
        _chunk("a", "incident response procedures", document_id="NLC-ENG-007"),
        _chunk("b", "incident response procedures", document_id="NLC-ENG-999"),
    ]
    retriever = _build_retriever(tmp_path, chunks)

    response = retriever.retrieve(
        RetrievalQuery(text="incident response", top_k=5, filters={"document_id": "NLC-ENG-999"})
    )

    assert len(response.results) == 1
    assert response.results[0].chunk.chunk_id == "b"


def test_empty_index_returns_no_results(tmp_path):
    provider = LocalHashingEmbeddingProvider(dimensions=32)
    store = LocalVectorStore(tmp_path / "store")
    retriever = Retriever(provider, store)

    response = retriever.retrieve(RetrievalQuery(text="anything", top_k=5))

    assert response.results == []
    assert response.diagnostics.total_indexed_chunks == 0
