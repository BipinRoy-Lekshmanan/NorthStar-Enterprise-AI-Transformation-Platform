"""Tests for `app.frontend.api_client.ApiClient` -- headers, error
handling, and response parsing (Milestone 7). No real network calls;
`httpx.request` is monkeypatched to return crafted `httpx.Response`
objects, never a live server.
"""

import httpx
import pytest

from app.frontend.api_client import ApiClient, ApiClientError


def test_headers_include_api_key_when_set():
    client = ApiClient(api_key="my-key")
    assert client._headers() == {"X-API-Key": "my-key"}


def test_headers_empty_when_no_api_key():
    client = ApiClient(api_key=None)
    assert client._headers() == {}


def test_successful_request_parses_json(monkeypatch):
    def fake_request(method, url, **kwargs):
        assert method == "GET"
        assert url == "http://test/api/v1/health"
        return httpx.Response(200, json={"status": "ok"})

    monkeypatch.setattr("app.frontend.api_client.httpx.request", fake_request)
    client = ApiClient(base_url="http://test")
    assert client.health() == {"status": "ok"}


def test_error_response_raises_api_client_error_with_code_and_message(monkeypatch):
    def fake_request(method, url, **kwargs):
        return httpx.Response(
            404,
            json={"error": {"code": "NOT_FOUND", "message": "Unknown advisor 'x'.", "details": {}, "request_id": "r1"}},
        )

    monkeypatch.setattr("app.frontend.api_client.httpx.request", fake_request)
    client = ApiClient(base_url="http://test")
    with pytest.raises(ApiClientError) as exc_info:
        client.current_user()
    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "NOT_FOUND"
    assert exc_info.value.message == "Unknown advisor 'x'."


def test_connect_error_raises_friendly_api_client_error(monkeypatch):
    def fake_request(method, url, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("app.frontend.api_client.httpx.request", fake_request)
    client = ApiClient(base_url="http://test")
    with pytest.raises(ApiClientError, match="Could not connect"):
        client.health()


def test_timeout_raises_friendly_api_client_error(monkeypatch):
    def fake_request(method, url, **kwargs):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("app.frontend.api_client.httpx.request", fake_request)
    client = ApiClient(base_url="http://test")
    with pytest.raises(ApiClientError, match="timed out"):
        client.health()


def test_ask_query_posts_json_payload(monkeypatch):
    captured = {}

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return httpx.Response(200, json={"answer": "..."})

    monkeypatch.setattr("app.frontend.api_client.httpx.request", fake_request)
    client = ApiClient(base_url="http://test")
    client.ask_query(question="hi", advisor="auto")

    assert captured["method"] == "POST"
    assert captured["url"] == "http://test/api/v1/query"
    assert captured["json"] == {"question": "hi", "advisor": "auto"}


def test_malformed_error_body_falls_back_to_response_text(monkeypatch):
    def fake_request(method, url, **kwargs):
        return httpx.Response(500, text="Internal Server Error")

    monkeypatch.setattr("app.frontend.api_client.httpx.request", fake_request)
    client = ApiClient(base_url="http://test")
    with pytest.raises(ApiClientError) as exc_info:
        client.health()
    assert exc_info.value.status_code == 500


def test_base_url_trailing_slash_is_stripped():
    client = ApiClient(base_url="http://test/")
    assert client.base_url == "http://test"


def test_list_advisors_calls_the_right_endpoint(monkeypatch):
    def fake_request(method, url, **kwargs):
        assert method == "GET"
        assert url == "http://test/api/v1/advisors"
        return httpx.Response(200, json=[{"advisor_id": "testing"}])

    monkeypatch.setattr("app.frontend.api_client.httpx.request", fake_request)
    client = ApiClient(base_url="http://test")
    assert client.list_advisors() == [{"advisor_id": "testing"}]


def test_get_advisor_calls_the_right_endpoint(monkeypatch):
    def fake_request(method, url, **kwargs):
        assert method == "GET"
        assert url == "http://test/api/v1/advisors/testing"
        return httpx.Response(200, json={"advisor_id": "testing"})

    monkeypatch.setattr("app.frontend.api_client.httpx.request", fake_request)
    client = ApiClient(base_url="http://test")
    assert client.get_advisor("testing") == {"advisor_id": "testing"}


def test_query_advisor_posts_to_the_right_endpoint(monkeypatch):
    captured = {}

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return httpx.Response(200, json={"answer": "..."})

    monkeypatch.setattr("app.frontend.api_client.httpx.request", fake_request)
    client = ApiClient(base_url="http://test")
    client.query_advisor("testing", question="hi")

    assert captured["method"] == "POST"
    assert captured["url"] == "http://test/api/v1/advisors/testing/query"
    assert captured["json"] == {"question": "hi"}


def test_preview_routing_posts_question(monkeypatch):
    captured = {}

    def fake_request(method, url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return httpx.Response(200, json={"primary_advisor": "testing"})

    monkeypatch.setattr("app.frontend.api_client.httpx.request", fake_request)
    client = ApiClient(base_url="http://test")
    result = client.preview_routing("What testing evidence is required?")

    assert captured["url"] == "http://test/api/v1/advisors/route"
    assert captured["json"] == {"question": "What testing evidence is required?"}
    assert result == {"primary_advisor": "testing"}


def test_list_documents_passes_pagination_and_filters(monkeypatch):
    captured = {}

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return httpx.Response(200, json={"items": [], "page": 1, "page_size": 25, "total_items": 0, "total_pages": 0})

    monkeypatch.setattr("app.frontend.api_client.httpx.request", fake_request)
    client = ApiClient(base_url="http://test")
    client.list_documents(page=2, page_size=10, status="Draft", owner="")

    assert captured["method"] == "GET"
    assert captured["url"] == "http://test/api/v1/knowledge/documents"
    assert captured["params"] == {"page": 2, "page_size": 10, "status": "Draft"}


def test_get_document_calls_the_right_endpoint(monkeypatch):
    def fake_request(method, url, **kwargs):
        assert method == "GET"
        assert url == "http://test/api/v1/knowledge/documents/NLC-ENG-005"
        return httpx.Response(200, json={"document_id": "NLC-ENG-005"})

    monkeypatch.setattr("app.frontend.api_client.httpx.request", fake_request)
    client = ApiClient(base_url="http://test")
    assert client.get_document("NLC-ENG-005") == {"document_id": "NLC-ENG-005"}


def test_knowledge_stats_calls_the_right_endpoint(monkeypatch):
    def fake_request(method, url, **kwargs):
        assert url == "http://test/api/v1/knowledge/stats"
        return httpx.Response(200, json={"document_count": 2})

    monkeypatch.setattr("app.frontend.api_client.httpx.request", fake_request)
    client = ApiClient(base_url="http://test")
    assert client.knowledge_stats() == {"document_count": 2}


def test_search_knowledge_posts_to_the_right_endpoint(monkeypatch):
    captured = {}

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return httpx.Response(200, json={"results": []})

    monkeypatch.setattr("app.frontend.api_client.httpx.request", fake_request)
    client = ApiClient(base_url="http://test")
    client.search_knowledge(question="hi", top_k=5)

    assert captured["method"] == "POST"
    assert captured["url"] == "http://test/api/v1/knowledge/search"
    assert captured["json"] == {"question": "hi", "top_k": 5}


def test_run_ingestion_posts_to_the_right_endpoint(monkeypatch):
    def fake_request(method, url, **kwargs):
        assert method == "POST"
        assert url == "http://test/api/v1/knowledge/ingest"
        return httpx.Response(200, json={"documents_loaded": 2})

    monkeypatch.setattr("app.frontend.api_client.httpx.request", fake_request)
    client = ApiClient(base_url="http://test")
    assert client.run_ingestion() == {"documents_loaded": 2}


def test_run_index_posts_to_the_right_endpoint(monkeypatch):
    def fake_request(method, url, **kwargs):
        assert method == "POST"
        assert url == "http://test/api/v1/knowledge/index"
        return httpx.Response(200, json={"added": 0})

    monkeypatch.setattr("app.frontend.api_client.httpx.request", fake_request)
    client = ApiClient(base_url="http://test")
    assert client.run_index() == {"added": 0}


def test_run_rebuild_posts_confirmation_phrase(monkeypatch):
    captured = {}

    def fake_request(method, url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return httpx.Response(200, json={"added": 2})

    monkeypatch.setattr("app.frontend.api_client.httpx.request", fake_request)
    client = ApiClient(base_url="http://test")
    client.run_rebuild("REBUILD")

    assert captured["url"] == "http://test/api/v1/knowledge/rebuild"
    assert captured["json"] == {"confirmation": "REBUILD"}
