"""Tests for `app.api.middleware.request_context` (Milestones 7-8):
request-id generation/echoing, the length cap on a client-supplied id
(Milestone 8), response-timing header, and contextvar propagation into
`app.config.logging` for the duration of the request.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.middleware.request_context import MAX_REQUEST_ID_LENGTH, RequestContextMiddleware
from app.config.logging import get_request_id


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/probe")
    def probe():
        return {"request_id_in_contextvar": get_request_id()}

    return app


def test_generates_a_request_id_when_none_supplied():
    with TestClient(_build_app()) as client:
        response = client.get("/probe")
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert len(response.headers["X-Request-ID"]) == 32  # uuid4().hex


def test_echoes_a_valid_incoming_request_id():
    with TestClient(_build_app()) as client:
        response = client.get("/probe", headers={"X-Request-ID": "caller-supplied-id"})
    assert response.headers["X-Request-ID"] == "caller-supplied-id"


def test_rejects_an_excessively_long_incoming_request_id():
    too_long = "x" * (MAX_REQUEST_ID_LENGTH + 1)
    with TestClient(_build_app()) as client:
        response = client.get("/probe", headers={"X-Request-ID": too_long})
    assert response.headers["X-Request-ID"] != too_long
    assert len(response.headers["X-Request-ID"]) == 32


def test_accepts_a_request_id_at_exactly_the_length_cap():
    exactly_max = "y" * MAX_REQUEST_ID_LENGTH
    with TestClient(_build_app()) as client:
        response = client.get("/probe", headers={"X-Request-ID": exactly_max})
    assert response.headers["X-Request-ID"] == exactly_max


def test_response_includes_timing_header():
    with TestClient(_build_app()) as client:
        response = client.get("/probe")
    assert float(response.headers["X-Response-Time-Ms"]) >= 0


def test_request_id_is_available_via_contextvar_during_the_request():
    with TestClient(_build_app()) as client:
        response = client.get("/probe", headers={"X-Request-ID": "ctx-test-id"})
    assert response.json()["request_id_in_contextvar"] == "ctx-test-id"


def test_contextvar_does_not_leak_after_the_request_completes():
    with TestClient(_build_app()) as client:
        client.get("/probe", headers={"X-Request-ID": "leaky-id"})
    assert get_request_id() is None
