"""Thin HTTP client for the Northstar platform API (Milestone 7).

The *only* module in the Streamlit frontend that knows the backend URL
or API key -- every page calls a method here, never `httpx` directly.
Raises `ApiClientError` (carrying the server's error code/message when
available) rather than letting a raw connection/HTTP exception reach a
page; pages catch this one exception type and render a friendly banner.
"""

from __future__ import annotations

from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 30.0


class ApiClientError(Exception):
    def __init__(self, message: str, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class ApiClient:
    def __init__(
        self, base_url: str = DEFAULT_BASE_URL, api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key} if self.api_key else {}

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        url = f"{self.base_url}{path}"
        try:
            response = httpx.request(method, url, headers=self._headers(), timeout=self.timeout, **kwargs)
        except httpx.ConnectError as exc:
            raise ApiClientError(f"Could not connect to the API at {self.base_url}. Is it running?") from exc
        except httpx.TimeoutException as exc:
            raise ApiClientError(f"Request to {path} timed out after {self.timeout}s.") from exc

        if response.status_code >= 400:
            self._raise_for_error(response)

        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    def _raise_for_error(self, response: httpx.Response) -> None:
        message = response.text
        code = None
        try:
            body = response.json()
            error = body.get("error", {})
            message = error.get("message", response.text)
            code = error.get("code")
        except Exception:
            pass
        raise ApiClientError(message, status_code=response.status_code, code=code)

    # -- health / auth -----------------------------------------------------------------

    def health(self) -> dict:
        return self._request("GET", "/api/v1/health")

    def current_user(self) -> dict:
        return self._request("GET", "/api/v1/auth/me")

    # -- query -----------------------------------------------------------------

    def ask_query(self, **payload: Any) -> dict:
        return self._request("POST", "/api/v1/query", json=payload)

    # -- advisors -----------------------------------------------------------------

    def list_advisors(self) -> list[dict]:
        return self._request("GET", "/api/v1/advisors")

    def get_advisor(self, advisor_id: str) -> dict:
        return self._request("GET", f"/api/v1/advisors/{advisor_id}")

    def query_advisor(self, advisor_id: str, **payload: Any) -> dict:
        return self._request("POST", f"/api/v1/advisors/{advisor_id}/query", json=payload)

    def preview_routing(self, question: str) -> dict:
        return self._request("POST", "/api/v1/advisors/route", json={"question": question})

    # -- knowledge -----------------------------------------------------------------

    def list_documents(self, page: int = 1, page_size: int = 25, **filters: Any) -> dict:
        params = {"page": page, "page_size": page_size, **{k: v for k, v in filters.items() if v}}
        return self._request("GET", "/api/v1/knowledge/documents", params=params)

    def get_document(self, document_id: str) -> dict:
        return self._request("GET", f"/api/v1/knowledge/documents/{document_id}")

    def knowledge_stats(self) -> dict:
        return self._request("GET", "/api/v1/knowledge/stats")

    def search_knowledge(self, **payload: Any) -> dict:
        return self._request("POST", "/api/v1/knowledge/search", json=payload)

    def run_ingestion(self) -> dict:
        return self._request("POST", "/api/v1/knowledge/ingest")

    def run_index(self) -> dict:
        return self._request("POST", "/api/v1/knowledge/index")

    def run_rebuild(self, confirmation: str) -> dict:
        return self._request("POST", "/api/v1/knowledge/rebuild", json={"confirmation": confirmation})

    # -- workflows -----------------------------------------------------------------

    def list_workflows(self) -> list[dict]:
        return self._request("GET", "/api/v1/workflows")

    def get_workflow(self, workflow_id: str) -> dict:
        return self._request("GET", f"/api/v1/workflows/{workflow_id}")

    def list_workflow_examples(self, workflow_id: str) -> list[dict]:
        return self._request("GET", f"/api/v1/workflows/{workflow_id}/examples")

    def execute_workflow(self, workflow_id: str, inputs: dict) -> dict:
        return self._request("POST", f"/api/v1/workflows/{workflow_id}/execute", json={"inputs": inputs})

    def list_executions(self, workflow_id: str | None = None, page: int = 1, page_size: int = 25) -> dict:
        params = {"page": page, "page_size": page_size}
        if workflow_id:
            params["workflow_id"] = workflow_id
        return self._request("GET", "/api/v1/workflows/executions", params=params)

    def get_execution(self, execution_id: str) -> dict:
        return self._request("GET", f"/api/v1/workflows/executions/{execution_id}")

    def resume_execution(self, execution_id: str) -> dict:
        return self._request("POST", f"/api/v1/workflows/executions/{execution_id}/resume")

    def cancel_execution(self, execution_id: str) -> dict:
        return self._request("POST", f"/api/v1/workflows/executions/{execution_id}/cancel")

    def get_workflow_report(self, execution_id: str) -> dict:
        return self._request("GET", f"/api/v1/workflows/executions/{execution_id}/report")

    # -- approvals -----------------------------------------------------------------

    def list_pending_approvals(self) -> list[dict]:
        return self._request("GET", "/api/v1/approvals")

    def decide_approval(self, execution_id: str, decision: str, reviewer: str | None = None, comments: str | None = None) -> dict:
        return self._request(
            "POST", f"/api/v1/approvals/{execution_id}/decide",
            json={"decision": decision, "reviewer": reviewer, "comments": comments},
        )

    # -- evaluation -----------------------------------------------------------------

    def run_evaluation(self, category: str) -> dict:
        return self._request("POST", "/api/v1/evaluation/runs", json={"category": category})

    def list_evaluation_runs(self, category: str | None = None, page: int = 1, page_size: int = 25) -> dict:
        params = {"page": page, "page_size": page_size}
        if category:
            params["category"] = category
        return self._request("GET", "/api/v1/evaluation/runs", params=params)

    def get_evaluation_run(self, run_id: str) -> dict:
        return self._request("GET", f"/api/v1/evaluation/runs/{run_id}")

    # -- platform -----------------------------------------------------------------

    def health_detail(self) -> dict:
        return self._request("GET", "/api/v1/platform/health")

    def audit_events(self, limit: int = 50) -> list[dict]:
        return self._request("GET", "/api/v1/platform/audit", params={"limit": limit})
