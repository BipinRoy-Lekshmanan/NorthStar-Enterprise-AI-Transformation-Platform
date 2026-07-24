"""End-to-end tests for all 5 catalog workflows (Milestone 6): real
`WorkflowEngine` + real catalog `WorkflowDefinition`s (unchanged
Milestone 1-5 infrastructure underneath) + `FakeModelProvider` + a
fixture KB covering every advisor document each workflow touches --
no network, no API key.
"""

from app.config.settings import IngestionSettings, RagSettings
from app.embeddings.indexer import Indexer
from app.embeddings.vector_store import LocalVectorStore
from app.embeddings.vectorizer import LocalHashingEmbeddingProvider
from app.ingestion.pipeline import IngestionPipeline
from app.models.workflow import ApprovalDecision
from app.rag.context_builder import ContextBuilder
from app.rag.pipeline import RagService
from app.rag.retriever import Retriever
from app.services.llm_service import FakeModelProvider
from app.workflows.engine import WorkflowEngine
from app.workflows.store import WorkflowStore
from app.workflows.synthesis import dedupe_citations


def _rag_settings(**overrides):
    defaults = dict(
        llm_provider="fake", llm_model="fake-echo-v1", llm_api_key=None,
        llm_temperature=0.0, llm_max_output_tokens=1024, llm_timeout_seconds=30.0,
        context_max_characters=6000, context_max_chunks=6, context_min_score=0.0,
        max_question_length=2000, insufficient_context_min_results=1, insufficient_context_min_score=0.0,
    )
    defaults.update(overrides)
    return RagSettings(**defaults)


_DOCUMENTS = {
    "11_Architecture_Principles.md": ("NLC-ENG-002", "Architecture Principles"),
    "12_AI_Engineering_Standards.md": ("NLC-ENG-003", "AI Engineering Standards"),
    "13_DevSecOps_Standards.md": ("NLC-ENG-004", "DevSecOps Standards"),
    "14_Testing_Strategy.md": ("NLC-ENG-005", "Testing Strategy"),
    "15_Release_Management.md": ("NLC-ENG-006", "Release Management"),
    "16_Incident_Management.md": ("NLC-ENG-007", "Incident Management"),
    "17_Platform_Engineering.md": ("NLC-ENG-008", "Platform Engineering"),
    "18_Developer_Experience.md": ("NLC-ENG-009", "Developer Experience"),
}


def _seed_kb(tmp_path):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    for filename, (document_id, title) in _DOCUMENTS.items():
        (kb_dir / filename).write_text(
            f"---\ndocument_id: {document_id}\ntitle: {title}\n---\n\n"
            f"# {title}\n\n## Standards\n\n"
            + (f"{title} defines the relevant Northstar standard for this area. " * 20),
            encoding="utf-8",
        )
    return kb_dir


def _build_engine(tmp_path):
    kb_dir = _seed_kb(tmp_path)
    ingestion_settings = IngestionSettings(
        knowledge_base_dirs=(kb_dir,), supported_extensions=(".md",),
        chunk_size=500, chunk_overlap=50, log_level="INFO", output_dir=tmp_path / "processed",
    )
    pipeline = IngestionPipeline(settings=ingestion_settings)
    provider = LocalHashingEmbeddingProvider(dimensions=128)
    vector_store = LocalVectorStore(tmp_path / "vstore")
    Indexer(provider, vector_store).index_from_pipeline(pipeline)
    retriever = Retriever(provider, vector_store)
    context_builder = ContextBuilder(
        max_characters=6000, max_chunks=6, min_score=0.0, insufficient_min_results=1, insufficient_min_score=0.0,
    )
    service = RagService(retriever, context_builder, FakeModelProvider(), _rag_settings(), default_top_k=10)
    store = WorkflowStore(tmp_path / "workflow_store")
    return WorkflowEngine(service, store, _rag_settings())


def _approve_if_paused(engine, execution):
    if execution.status == "awaiting_approval":
        return engine.approve(execution.execution_id, ApprovalDecision(decision="approve", reviewer="test"))
    return execution


def test_architecture_review_end_to_end(tmp_path):
    engine = _build_engine(tmp_path)
    inputs = {
        "solution_name": "Loan Payment Notification Platform",
        "business_objective": "Send real-time payment confirmation notifications",
        "architecture_description": "A Kubernetes-hosted synchronous microservice calling five downstream systems.",
        "data_classification": "Confidential",
        "deployment_target": "Kubernetes",
        "expected_volume": "2 million notifications per day",
        "known_constraints": ["Must use the existing enterprise API gateway"],
    }
    execution = engine.run("architecture_review", inputs)
    assert execution.status == "awaiting_approval"  # always pauses before synthesis

    final = _approve_if_paused(engine, execution)
    assert final.status == "completed"
    assert dedupe_citations(final.stage_results)

    report_stage = next(r for r in final.stage_results if r.stage_id == "final_architecture_report")
    assert "Sources" in report_stage.structured_output["report_sections"]


def test_ai_solution_review_end_to_end(tmp_path):
    engine = _build_engine(tmp_path)
    inputs = {
        "use_case": "Loan document summarization",
        "business_objective": "Reduce underwriter review time",
        "model_provider": "OpenAI",
        "data_sensitivity": "Confidential",
        "human_review_process": "Underwriter reviews every summary before use",
        "evaluation_approach": "Golden-set accuracy evaluation before release",
    }
    execution = engine.run("ai_solution_review", inputs)
    # No blocking evidence gap (both human_review_process and evaluation_approach given) -> no pause.
    assert execution.status == "completed"
    assert dedupe_citations(execution.stage_results)


def test_production_readiness_review_end_to_end(tmp_path):
    engine = _build_engine(tmp_path)
    inputs = {
        "release_name": "Loan Notification Service v2",
        "services_affected": ["notification-service"],
        "business_impact": "Improves notification latency.",
        "deployment_strategy": "canary",
        "test_evidence": "Full regression suite passed.",
        "security_evidence": "Security review completed.",
        # rollback_plan intentionally omitted -> blocking evidence gap.
    }
    execution = engine.run("production_readiness_review", inputs)
    assert execution.status == "awaiting_approval"

    final = _approve_if_paused(engine, execution)
    assert final.status == "completed"

    report_stage = next(r for r in final.stage_results if r.stage_id == "release_recommendation")
    assert report_stage.structured_output["report_sections"]["Recommendation"] == "INSUFFICIENT_EVIDENCE"


def test_incident_review_end_to_end(tmp_path):
    engine = _build_engine(tmp_path)
    inputs = {
        "incident_title": "Payment API latency spike",
        "severity": "Sev-2",
        "start_time": "2026-07-20T10:00:00Z",
        "customer_impact": "Delayed payment confirmations for 15 minutes",
        "systems_affected": ["payment-api"],
        "timeline": ["10:00 detected", "11:30 resolved"],
        "security_related": "no",
    }
    execution = engine.run("incident_review", inputs)
    security_stage = next(r for r in execution.stage_results if r.stage_id == "security_review")
    assert security_stage.status == "skipped"  # security_related=no
    assert execution.status == "awaiting_approval"  # always pauses

    final = _approve_if_paused(engine, execution)
    assert final.status == "completed"
    assert dedupe_citations(final.stage_results)


def test_executive_ai_transformation_assessment_end_to_end(tmp_path):
    engine = _build_engine(tmp_path)
    inputs = {
        "business_priorities": ["Reduce loan processing time"],
        "current_ai_capabilities": "Pilot RAG assistant for engineering knowledge base",
        "target_timeline": "18 months",
        "desired_business_outcomes": ["Faster loan decisions"],
    }
    execution = engine.run("executive_ai_transformation_assessment", inputs)
    assert execution.status == "awaiting_approval"  # always pauses before roadmap synthesis

    final = _approve_if_paused(engine, execution)
    assert final.status == "completed"
    assert dedupe_citations(final.stage_results)

    report_stage = next(r for r in final.stage_results if r.stage_id == "final_executive_assessment")
    # FakeModelProvider's placeholder text has no section headers to split on, so only
    # the first declared section and the deterministically-computed Sources section are
    # populated (see app.workflows.report's header-matching fallback) -- not every
    # declared header is guaranteed a key when the synthesis text carries no structure.
    report_sections = report_stage.structured_output["report_sections"]
    assert "Executive Summary" in report_sections
    assert "Sources" in report_sections
