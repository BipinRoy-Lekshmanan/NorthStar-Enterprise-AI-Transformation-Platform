"""Tests for `app.api.errors` -- the error envelope, request-ID/timing
middleware, and domain-exception-to-HTTP mapping (Milestone 7). Uses a
small standalone FastAPI app (not the real `app.api.main.app`) so each
test can raise whatever exception it needs without touching real
services.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.registry import UnknownAdvisorError
from app.api.errors import ApiError, ErrorCode, register_exception_handlers
from app.api.middleware.request_context import RequestContextMiddleware
from app.config.settings import ConfigurationError
from app.embeddings.vector_store import VectorStoreError
from app.rag.pipeline import QuestionValidationError
from app.services.llm_service import ModelUnavailableError
from app.workflows.engine import WorkflowEngineError
from app.workflows.registry import UnknownWorkflowError
from app.workflows.store import WorkflowStoreError


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    @app.get("/raise/api-error")
    def raise_api_error():
        raise ApiError(403, ErrorCode.FORBIDDEN, "You cannot do that.", details={"required_role": "reviewer"})

    @app.get("/raise/question-validation")
    def raise_question_validation():
        raise QuestionValidationError("Question must not be empty.")

    @app.get("/raise/unknown-advisor")
    def raise_unknown_advisor():
        raise UnknownAdvisorError("Unknown advisor 'bogus'. Available: testing, release")

    @app.get("/raise/unknown-workflow")
    def raise_unknown_workflow():
        raise UnknownWorkflowError("Unknown workflow 'bogus'.")

    @app.get("/raise/workflow-store")
    def raise_workflow_store():
        raise WorkflowStoreError("No workflow execution found for id 'abc'.")

    @app.get("/raise/workflow-engine")
    def raise_workflow_engine():
        raise WorkflowEngineError("Execution 'abc' has terminal status 'completed'.")

    @app.get("/raise/model-provider")
    def raise_model_provider():
        raise ModelUnavailableError("The model provider is unavailable.")

    @app.get("/raise/vector-store")
    def raise_vector_store():
        raise VectorStoreError("Dimension mismatch.")

    @app.get("/raise/configuration")
    def raise_configuration():
        raise ConfigurationError("LLM_PROVIDER is invalid.")

    @app.get("/ok")
    def ok():
        return {"status": "ok"}

    return app


client = TestClient(_build_test_app())


def test_successful_response_carries_request_id_and_timing_headers():
    response = client.get("/ok")
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")
    assert response.headers.get("X-Response-Time-Ms")


def test_incoming_request_id_is_echoed_back():
    response = client.get("/ok", headers={"X-Request-ID": "my-custom-id"})
    assert response.headers["X-Request-ID"] == "my-custom-id"


def test_api_error_produces_matching_envelope():
    response = client.get("/raise/api-error")
    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "FORBIDDEN"
    assert body["error"]["message"] == "You cannot do that."
    assert body["error"]["details"] == {"required_role": "reviewer"}
    assert body["error"]["request_id"]


def test_404_not_found_produces_error_envelope():
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_question_validation_error_maps_to_400_validation_error():
    response = client.get("/raise/question-validation")
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Question must not be empty."


def test_unknown_advisor_error_maps_to_404_without_keyerror_quoting():
    response = client.get("/raise/unknown-advisor")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    # KeyError.__str__ would otherwise wrap this in an extra pair of quotes.
    assert body["error"]["message"] == "Unknown advisor 'bogus'. Available: testing, release"
    assert not body["error"]["message"].startswith('"')


def test_unknown_workflow_error_maps_to_404():
    response = client.get("/raise/unknown-workflow")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_workflow_store_error_maps_to_404():
    response = client.get("/raise/workflow-store")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_workflow_engine_error_maps_to_409_workflow_error():
    response = client.get("/raise/workflow-engine")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKFLOW_ERROR"


def test_model_provider_error_maps_to_502():
    response = client.get("/raise/model-provider")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODEL_PROVIDER_ERROR"


def test_vector_store_error_maps_to_500():
    response = client.get("/raise/vector-store")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "VECTOR_STORE_ERROR"


def test_configuration_error_maps_to_500():
    response = client.get("/raise/configuration")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "CONFIGURATION_ERROR"


def test_no_stack_trace_leaks_into_error_response():
    response = client.get("/raise/workflow-engine")
    body_text = response.text
    assert "Traceback" not in body_text
    assert "app/workflows/engine.py" not in body_text
    assert __file__ not in body_text
