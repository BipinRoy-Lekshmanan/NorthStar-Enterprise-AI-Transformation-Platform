"""Unit tests for the data-classification guardrail helpers in
`app.api.services.knowledge_service` (Milestone 8): `is_restricted`,
`exclude_restricted_documents`, `restricted_document_ids`,
`restricted_ids_for_role`, `filter_restricted_citations`, and
`search_knowledge`'s `exclude_document_ids` parameter.
"""

from dataclasses import dataclass

from app.api.services.knowledge_service import (
    RESTRICTED_MINIMUM_ROLE,
    DocumentSummary,
    exclude_restricted_documents,
    filter_restricted_citations,
    is_restricted,
    restricted_document_ids,
    restricted_ids_for_role,
    search_knowledge,
)
from app.auth.roles import Role
from app.config.settings import IngestionSettings, RetrievalSettings
from app.embeddings.indexer import Indexer, build_provider_and_store
from app.ingestion.pipeline import IngestionPipeline


def _doc(document_id, classification):
    return DocumentSummary(
        document_id=document_id, title="t", source_file="f.md", source_path="f.md", domain="d",
        owner=None, status=None, classification=classification,
    )


def test_is_restricted_is_case_insensitive():
    assert is_restricted("Restricted") is True
    assert is_restricted("RESTRICTED") is True
    assert is_restricted("restricted") is True


def test_is_restricted_false_for_other_classifications():
    assert is_restricted("Internal") is False
    assert is_restricted("Confidential") is False
    assert is_restricted("Public") is False
    assert is_restricted(None) is False


def test_exclude_restricted_documents_keeps_only_non_restricted():
    documents = [_doc("d1", "Internal"), _doc("d2", "Restricted"), _doc("d3", None)]
    kept = exclude_restricted_documents(documents)
    assert [d.document_id for d in kept] == ["d1", "d3"]


def test_restricted_minimum_role_is_administrator():
    assert RESTRICTED_MINIMUM_ROLE == Role.ADMINISTRATOR


def test_restricted_ids_for_role_returns_empty_set_for_administrator(tmp_path):
    assert restricted_ids_for_role(Role.ADMINISTRATOR, _ingestion_settings(tmp_path)) == set()


def test_restricted_ids_for_role_returns_real_set_for_lower_roles(tmp_path):
    ingestion_settings = _ingestion_settings(tmp_path, with_restricted=True)
    for role in (Role.VIEWER, Role.ENGINEER, Role.REVIEWER):
        ids = restricted_ids_for_role(role, ingestion_settings)
        assert ids == {"RESTRICTED-DOC"}


def test_filter_restricted_citations_removes_matching_document_ids():
    @dataclass
    class _Citation:
        document_id: str | None

    citations = [_Citation("d1"), _Citation("d2"), _Citation(None)]
    filtered = filter_restricted_citations(citations, {"d2"})
    assert [c.document_id for c in filtered] == ["d1", None]


def test_filter_restricted_citations_is_a_no_op_for_an_empty_restricted_set():
    @dataclass
    class _Citation:
        document_id: str | None

    citations = [_Citation("d1")]
    assert filter_restricted_citations(citations, set()) is citations


def _seed_kb(kb_dir, with_restricted=False):
    kb_dir.mkdir(exist_ok=True)
    (kb_dir / "public_doc.md").write_text(
        "---\ndocument_id: PUBLIC-DOC\ntitle: Public Doc\nclassification: Internal\n---\n\n"
        "# Public Doc\n\n## Section\n\n" + ("Ordinary internal content about testing strategy. " * 15),
        encoding="utf-8",
    )
    if with_restricted:
        (kb_dir / "restricted_doc.md").write_text(
            "---\ndocument_id: RESTRICTED-DOC\ntitle: Restricted Doc\nclassification: Restricted\n---\n\n"
            "# Restricted Doc\n\n## Section\n\n" + ("Highly sensitive restricted content. " * 15),
            encoding="utf-8",
        )
    return kb_dir


def _ingestion_settings(tmp_path, with_restricted=False):
    kb_dir = _seed_kb(tmp_path / "kb", with_restricted=with_restricted)
    return IngestionSettings(
        knowledge_base_dirs=(kb_dir,), supported_extensions=(".md",),
        chunk_size=500, chunk_overlap=50, log_level="INFO", output_dir=tmp_path / "processed",
    )


def test_restricted_document_ids_finds_only_restricted_documents(tmp_path):
    ingestion_settings = _ingestion_settings(tmp_path, with_restricted=True)
    assert restricted_document_ids(ingestion_settings) == {"RESTRICTED-DOC"}


def test_restricted_document_ids_empty_when_none_restricted(tmp_path):
    ingestion_settings = _ingestion_settings(tmp_path, with_restricted=False)
    assert restricted_document_ids(ingestion_settings) == set()


def test_search_knowledge_excludes_matching_document_ids(tmp_path):
    ingestion_settings = _ingestion_settings(tmp_path, with_restricted=True)
    retrieval_settings = RetrievalSettings(
        embedding_provider="local", embedding_model="local-hashing-v1", embedding_dimensions=128,
        vector_store_dir=tmp_path / "vector_store", retrieval_top_k=10, openai_api_key=None,
    )
    provider, store = build_provider_and_store(retrieval_settings)
    Indexer(provider, store).index_from_pipeline(IngestionPipeline(settings=ingestion_settings))

    from app.rag.retriever import Retriever

    retriever = Retriever(provider, store)

    unfiltered = search_knowledge(retriever, "sensitive restricted content", top_k=10)
    assert any(r.chunk.document_id == "RESTRICTED-DOC" for r in unfiltered.results)

    filtered = search_knowledge(
        retriever, "sensitive restricted content", top_k=10, exclude_document_ids={"RESTRICTED-DOC"},
    )
    assert all(r.chunk.document_id != "RESTRICTED-DOC" for r in filtered.results)
