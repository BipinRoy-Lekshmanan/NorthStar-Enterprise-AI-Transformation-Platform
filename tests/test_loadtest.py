"""Tests for `app.loadtest` (Milestone 8) -- the hand-rolled async
load-test harness.

The harness-correctness tests below drive `run_load_test` against a
real `create_app()` instance via `httpx.ASGITransport` (in-process, no
real socket) -- fast and deterministic, matching this suite's existing
TestClient-based conventions, and exercising the exact same code path
`python -m app.loadtest run` uses against a real socket. Lifespan
startup is triggered by entering `TestClient(app)` (which populates
`app.state.*`) before handing the same `app` object to an async
`httpx.AsyncClient(transport=httpx.ASGITransport(app=app))` -- safe
because everything the lifespan sets up here (`LockRegistry`, the
SQLite session factory, ...) is synchronous / thread-based, not bound
to a specific asyncio event loop.
"""

import asyncio
import json
import random

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.loadtest import cli as loadtest_cli
from app.loadtest.harness import (
    DEFAULT_SCENARIOS,
    RequestResult,
    Scenario,
    _build_report,
    _choose_scenario,
    _percentile,
    run_load_test,
)


def _seed_kb(tmp_path):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "policy.md").write_text(
        "---\ndocument_id: NLC-HR-001\ntitle: Remote Work Policy\n---\n\n# Remote Work Policy\n\n"
        + ("Employees may work remotely subject to manager approval. " * 15),
        encoding="utf-8",
    )
    return kb_dir


@pytest.fixture
def app(tmp_path, monkeypatch):
    users_file = tmp_path / "users.json"
    users_file.write_text(
        json.dumps(
            [
                {"api_key": "viewer-key-1", "username": "v1", "role": "viewer"},
                {"api_key": "viewer-key-2", "username": "v2", "role": "viewer"},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTH_USERS_FILE", str(users_file))
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit_log"))
    monkeypatch.setenv("KNOWLEDGE_BASE_DIRS", str(_seed_kb(tmp_path)))

    return create_app()


def test_run_load_test_against_real_app_via_asgi_transport(app):
    with TestClient(app):  # runs lifespan startup, populating app.state.*
        transport = httpx.ASGITransport(app=app)
        report = asyncio.run(
            run_load_test(
                base_url="http://testserver",
                api_keys=["viewer-key-1", "viewer-key-2"],
                duration_seconds=0.5,
                concurrency=4,
                request_timeout=5.0,
                transport=transport,
            )
        )

    assert report.total_requests > 0
    assert report.duration_seconds > 0
    assert report.requests_per_second > 0
    # "health" is unauthenticated and always succeeds -- guaranteed to
    # show up regardless of how the weighted random draw fell.
    assert "health" in report.by_scenario
    assert 200 in report.by_scenario["health"].status_codes
    # No connection errors / 5xx expected against a healthy in-process app.
    assert report.total_errors == 0


def test_run_load_test_rejects_non_positive_duration_or_concurrency():
    with pytest.raises(ValueError, match="concurrency"):
        asyncio.run(run_load_test(base_url="http://x", api_keys=[], duration_seconds=1.0, concurrency=0))

    with pytest.raises(ValueError, match="duration_seconds"):
        asyncio.run(run_load_test(base_url="http://x", api_keys=[], duration_seconds=0.0, concurrency=1))


# -- _percentile -----------------------------------------------------------------------------


def test_percentile_of_empty_list_is_zero():
    assert _percentile([], 50) == 0.0


def test_percentile_of_single_value_is_that_value():
    assert _percentile([42.0], 99) == 42.0


def test_percentile_interpolates_between_neighbors():
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert _percentile(values, 50) == 30.0
    assert _percentile(values, 0) == 10.0
    assert _percentile(values, 100) == 50.0


# -- _choose_scenario -----------------------------------------------------------------------------


def test_choose_scenario_favors_higher_weight():
    heavy = Scenario(name="heavy", method="GET", path="/heavy", weight=99)
    light = Scenario(name="light", method="GET", path="/light", weight=1)
    rng = random.Random(1234)

    picks = [_choose_scenario((heavy, light), rng).name for _ in range(200)]

    assert picks.count("heavy") > 180


# -- error handling -----------------------------------------------------------------------------


class _AlwaysFailsTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):
        raise httpx.ConnectError("connection refused", request=request)


def test_connection_errors_are_captured_not_raised():
    report = asyncio.run(
        run_load_test(
            base_url="http://unreachable.invalid",
            api_keys=["some-key"],
            duration_seconds=0.2,
            concurrency=2,
            scenarios=(Scenario(name="health", method="GET", path="/api/v1/health"),),
            transport=_AlwaysFailsTransport(),
        )
    )

    assert report.total_requests > 0
    assert report.total_errors == report.total_requests
    assert report.by_scenario["health"].status_codes == {0: report.total_requests}


# -- CLI: format_report -----------------------------------------------------------------------------


def test_format_report_notes_rate_limiting_when_429_present():
    report = asyncio.run(
        run_load_test(
            base_url="http://x",
            api_keys=[],
            duration_seconds=0.05,
            concurrency=1,
            scenarios=(Scenario(name="s", method="GET", path="/s"),),
            transport=httpx.MockTransport(lambda request: httpx.Response(429)),
        )
    )
    text = loadtest_cli.format_report(report)
    assert "rate limiter" in text


def test_format_report_omits_rate_limit_note_without_429():
    report = asyncio.run(
        run_load_test(
            base_url="http://x",
            api_keys=[],
            duration_seconds=0.05,
            concurrency=1,
            scenarios=(Scenario(name="s", method="GET", path="/s"),),
            transport=httpx.MockTransport(lambda request: httpx.Response(200)),
        )
    )
    text = loadtest_cli.format_report(report)
    assert "rate limiter" not in text


# -- CLI: main() wiring -----------------------------------------------------------------------------


def test_cli_main_writes_json_report_and_returns_0(tmp_path, monkeypatch, capsys):
    async def _fake_run_load_test(**kwargs):
        return _build_report(
            [RequestResult(scenario="health", status_code=200, latency_ms=5.0)], elapsed_seconds=1.0
        )

    monkeypatch.setattr(loadtest_cli, "run_load_test", _fake_run_load_test)
    output_path = tmp_path / "report.json"

    exit_code = loadtest_cli.main(
        ["run", "--base-url", "http://x", "--duration", "1", "--concurrency", "1", "--output", str(output_path)]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Total requests: 1" in out
    assert "Full report written to" in out

    document = json.loads(output_path.read_text(encoding="utf-8"))
    assert document["total_requests"] == 1
    assert document["by_scenario"]["health"]["count"] == 1


def test_cli_main_returns_1_when_no_requests_completed(monkeypatch):
    async def _fake_run_load_test(**kwargs):
        return _build_report([], elapsed_seconds=1.0)

    monkeypatch.setattr(loadtest_cli, "run_load_test", _fake_run_load_test)

    exit_code = loadtest_cli.main(["run", "--base-url", "http://unreachable.invalid", "--duration", "1"])

    assert exit_code == 1


def test_default_scenarios_cover_a_representative_mix():
    names = {s.name for s in DEFAULT_SCENARIOS}
    assert names == {"health", "platform_info", "knowledge_list", "query"}
