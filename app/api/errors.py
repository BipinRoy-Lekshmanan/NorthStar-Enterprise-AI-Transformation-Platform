"""Consistent API error envelope + domain-exception mapping (Milestone 7).

Route handlers never try/except -- a fixed table of
`{ExceptionClass: (status_code, ErrorCode)}` is registered once, at app
startup, as FastAPI exception handlers, and every exception raised by
`app.api.services` bubbles up through it unmodified. This mirrors how
`app/workflows/cli.py` lets `WorkflowEngineError` bubble to one
top-level handler rather than catching per-command.

Stack traces are never included in the response body. They may still be
logged locally by uvicorn's own logging -- never returned to the caller.
"""

from __future__ import annotations

from enum import Enum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.agents.registry import UnknownAdvisorError
from app.api.services.knowledge_service import UnknownDocumentError
from app.config.settings import ConfigurationError
from app.embeddings.vector_store import VectorStoreError
from app.embeddings.vectorizer import EmbeddingProviderError
from app.evaluation.run_store import EvaluationRunStoreError
from app.operations.background import UnknownOperationError
from app.rag.pipeline import QuestionValidationError
from app.services.llm_service import ModelProviderError
from app.workflows.definitions import WorkflowDefinitionError
from app.workflows.engine import WorkflowEngineError
from app.workflows.registry import UnknownWorkflowError
from app.workflows.store import WorkflowStoreError


class ErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    MODEL_PROVIDER_ERROR = "MODEL_PROVIDER_ERROR"
    EMBEDDING_PROVIDER_ERROR = "EMBEDDING_PROVIDER_ERROR"
    VECTOR_STORE_ERROR = "VECTOR_STORE_ERROR"
    WORKFLOW_ERROR = "WORKFLOW_ERROR"
    WORKFLOW_AWAITING_APPROVAL = "WORKFLOW_AWAITING_APPROVAL"
    WORKFLOW_ALREADY_COMPLETED = "WORKFLOW_ALREADY_COMPLETED"
    APPROVAL_ERROR = "APPROVAL_ERROR"
    EVALUATION_ERROR = "EVALUATION_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    # Not in the milestone's explicit list but required by "clear
    # unauthorised and forbidden responses" -- kept in the same enum so
    # every error the API can return has exactly one code.
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    # Milestone 8: a concurrent conflicting operation (a rebuild already
    # running, a resume/approval already being processed for this
    # execution) was rejected rather than double-processed.
    CONCURRENCY_CONFLICT = "CONCURRENCY_CONFLICT"
    # Milestone 8: the same `Idempotency-Key` was reused on the same
    # endpoint with a materially different request body -- a client bug
    # (idempotency keys must be unique per distinct request), not a
    # retry.
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"


class ApiError(Exception):
    """Raised directly by API-layer code (auth, payload limits, workflow/
    approval preconditions) for a condition that maps onto one specific
    `ErrorCode`. Domain exceptions from Milestones 1-6 are *not* wrapped
    in this -- they're mapped by class in `_DOMAIN_EXCEPTION_MAP` below,
    so `app.api.services` functions never need to know about HTTP."""

    def __init__(self, status_code: int, code: ErrorCode, message: str, details: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


# Every exception class here is caught by class (not a shared base),
# so an unrelated KeyError/ValueError elsewhere is never accidentally
# reported as, say, a 404.
_DOMAIN_EXCEPTION_MAP: dict[type[Exception], tuple[int, ErrorCode]] = {
    QuestionValidationError: (400, ErrorCode.VALIDATION_ERROR),
    UnknownAdvisorError: (404, ErrorCode.NOT_FOUND),
    UnknownWorkflowError: (404, ErrorCode.NOT_FOUND),
    UnknownDocumentError: (404, ErrorCode.NOT_FOUND),
    UnknownOperationError: (404, ErrorCode.NOT_FOUND),
    WorkflowStoreError: (404, ErrorCode.NOT_FOUND),
    EvaluationRunStoreError: (404, ErrorCode.NOT_FOUND),
    WorkflowDefinitionError: (500, ErrorCode.INTERNAL_ERROR),
    WorkflowEngineError: (409, ErrorCode.WORKFLOW_ERROR),
    ModelProviderError: (502, ErrorCode.MODEL_PROVIDER_ERROR),
    EmbeddingProviderError: (502, ErrorCode.EMBEDDING_PROVIDER_ERROR),
    VectorStoreError: (500, ErrorCode.VECTOR_STORE_ERROR),
    ConfigurationError: (500, ErrorCode.CONFIGURATION_ERROR),
}


def _sanitize_validation_errors(errors: list[dict]) -> list[dict]:
    """Pydantic's `RequestValidationError.errors()` can include a `ctx`
    key whose value is the raw exception object from a custom
    `field_validator` (e.g. a `ValueError`) -- not JSON-serializable, and
    an internal detail we shouldn't return anyway. `msg` already carries
    the human-readable message, so only `type`/`loc`/`msg`/`input` are
    kept.
    """
    return [
        {"type": error.get("type"), "loc": error.get("loc"), "msg": error.get("msg"), "input": error.get("input")}
        for error in errors
    ]


def _error_body(code: ErrorCode, message: str, details: dict, request_id: str | None) -> dict:
    return {"error": {"code": code.value, "message": message, "details": details, "request_id": request_id}}


def _error_response(status_code: int, code: ErrorCode, message: str, details: dict, request_id: str | None) -> JSONResponse:
    """Builds the error JSON body and, additionally, an `X-Error-Code`
    response header -- lets `app.api.middleware.metrics` label the
    `api_errors_total` counter by error code without buffering/parsing
    the JSON response body."""
    response = JSONResponse(status_code=status_code, content=_error_body(code, message, details, request_id))
    response.headers["X-Error-Code"] = code.value
    return response


def register_exception_handlers(app: FastAPI) -> None:
    """Register one handler per exception type, once, at app startup."""

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        return _error_response(exc.status_code, exc.code, exc.message, exc.details, request_id)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        return _error_response(
            422, ErrorCode.VALIDATION_ERROR, "Request validation failed.",
            {"errors": _sanitize_validation_errors(exc.errors())}, request_id,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        code = ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.INTERNAL_ERROR
        return _error_response(exc.status_code, code, str(exc.detail), {}, request_id)

    for exc_class, (status_code, code) in _DOMAIN_EXCEPTION_MAP.items():
        _register_domain_handler(app, exc_class, status_code, code)


def _exception_message(exc: Exception) -> str:
    """`str(exc)` on a bare `KeyError`/similar (e.g. `UnknownAdvisorError`,
    `UnknownWorkflowError`) wraps the message in an extra pair of quotes
    (`KeyError.__str__` uses `repr()` of its first arg) -- use the raw
    first argument instead so error messages stay clean."""
    if exc.args:
        return str(exc.args[0])
    return str(exc)


def _register_domain_handler(app: FastAPI, exc_class: type[Exception], status_code: int, code: ErrorCode) -> None:
    async def handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        message = _exception_message(exc)
        return _error_response(status_code, code, message, {}, request_id)

    app.add_exception_handler(exc_class, handler)
