"""Load-test harness (Milestone 8).

httpx.AsyncClient + asyncio.gather over a fixed pool of "worker"
coroutines, rather than a third-party load tool (locust, k6, ...) --
httpx is already a dependency and the concurrency primitive needed
here (N coroutines hammering a shared client until a deadline) is a
few dozen lines, not worth a new tool for.

`run_load_test` accepts an optional `transport` so the exact same code
path can be driven two ways: a real `httpx.AsyncClient` against a real
socket (`python -m app.loadtest run --base-url http://...`, the actual
"realistic load" verification), or an in-process
`httpx.ASGITransport(app=...)` (what `tests/test_loadtest.py` uses --
fast and deterministic, no real socket, consistent with the rest of
this test suite's TestClient-based conventions).
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

import httpx


@dataclass(frozen=True)
class Scenario:
    name: str
    method: str
    path: str
    json_body: dict | None = None
    # Relative likelihood of this scenario being picked each iteration
    # -- not a fixed request count, since workers run until the time
    # deadline, not until N requests are sent.
    weight: int = 1


# A representative mix of the platform's real endpoints: two
# unauthenticated-or-viewer-level GETs that fall under the rate
# limiter's "default" category (120/min per actor), and one POST that
# falls under the "query" category's tighter 60/min per actor --
# deliberately included so a real run demonstrates the per-category
# limiter under load, not just raw throughput.
DEFAULT_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(name="health", method="GET", path="/api/v1/health", weight=2),
    Scenario(name="platform_info", method="GET", path="/api/v1/platform/info", weight=1),
    Scenario(name="knowledge_list", method="GET", path="/api/v1/knowledge/documents", weight=1),
    Scenario(
        name="query", method="POST", path="/api/v1/query",
        json_body={"question": "What is our remote work policy?"}, weight=2,
    ),
)


@dataclass
class RequestResult:
    scenario: str
    status_code: int
    latency_ms: float
    error: str | None = None


@dataclass
class ScenarioStats:
    count: int = 0
    errors: int = 0
    status_codes: dict[int, int] = field(default_factory=dict)
    latencies_ms: list[float] = field(default_factory=list)

    def percentiles(self) -> dict[str, float]:
        ordered = sorted(self.latencies_ms)
        return {"p50": _percentile(ordered, 50), "p95": _percentile(ordered, 95), "p99": _percentile(ordered, 99)}


@dataclass
class LoadTestReport:
    duration_seconds: float
    total_requests: int
    total_errors: int
    requests_per_second: float
    by_scenario: dict[str, ScenarioStats]


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (the same convention numpy's
    `percentile` default uses). Returns 0.0 for an empty sample rather
    than raising -- a scenario a short run never happened to hit is a
    normal, reportable outcome, not an error."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * (pct / 100)
    floor_index = int(rank)
    ceil_index = min(floor_index + 1, len(sorted_values) - 1)
    if floor_index == ceil_index:
        return sorted_values[floor_index]
    fraction = rank - floor_index
    return sorted_values[floor_index] + (sorted_values[ceil_index] - sorted_values[floor_index]) * fraction


def _choose_scenario(scenarios: Sequence[Scenario], rng: random.Random) -> Scenario:
    return rng.choices(scenarios, weights=[s.weight for s in scenarios], k=1)[0]  # nosec B311 -- traffic-mix sampling, not security-sensitive


async def _worker(
    worker_id: int,
    client: httpx.AsyncClient,
    scenarios: Sequence[Scenario],
    api_keys: Sequence[str],
    deadline: float,
    rng: random.Random,
    results: list[RequestResult],
) -> None:
    # `results` is a plain list shared across every worker coroutine
    # with no lock: asyncio runs one coroutine at a time and every
    # append below happens between (not across) `await` points, so
    # there's no interleaving that could corrupt it.
    key_index = worker_id
    while time.monotonic() < deadline:
        scenario = _choose_scenario(scenarios, rng)
        api_key = api_keys[key_index % len(api_keys)] if api_keys else None
        key_index += 1
        headers = {"x-api-key": api_key} if api_key else {}

        start = time.perf_counter()
        try:
            response = await client.request(scenario.method, scenario.path, headers=headers, json=scenario.json_body)
            latency_ms = (time.perf_counter() - start) * 1000
            results.append(RequestResult(scenario=scenario.name, status_code=response.status_code, latency_ms=latency_ms))
        except httpx.HTTPError as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            results.append(
                RequestResult(scenario=scenario.name, status_code=0, latency_ms=latency_ms, error=str(exc))
            )


def _build_report(results: list[RequestResult], elapsed_seconds: float) -> LoadTestReport:
    by_scenario: dict[str, ScenarioStats] = {}
    total_errors = 0
    for result in results:
        stats = by_scenario.setdefault(result.scenario, ScenarioStats())
        stats.count += 1
        stats.latencies_ms.append(result.latency_ms)
        stats.status_codes[result.status_code] = stats.status_codes.get(result.status_code, 0) + 1
        # 429 (rate-limited) is the system behaving as designed under
        # load, not a failure -- only connection errors and 5xx count
        # against total_errors.
        if result.error is not None or result.status_code >= 500:
            stats.errors += 1
            total_errors += 1

    return LoadTestReport(
        duration_seconds=elapsed_seconds,
        total_requests=len(results),
        total_errors=total_errors,
        requests_per_second=len(results) / elapsed_seconds if elapsed_seconds > 0 else 0.0,
        by_scenario=by_scenario,
    )


async def run_load_test(
    base_url: str,
    api_keys: Sequence[str],
    duration_seconds: float,
    concurrency: int,
    scenarios: Sequence[Scenario] = DEFAULT_SCENARIOS,
    request_timeout: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
    rng: random.Random | None = None,
) -> LoadTestReport:
    if concurrency <= 0:
        raise ValueError(f"concurrency must be a positive integer, got {concurrency}.")
    if duration_seconds <= 0:
        raise ValueError(f"duration_seconds must be positive, got {duration_seconds}.")

    rng = rng if rng is not None else random.Random()  # nosec B311 -- traffic-mix sampling, not security-sensitive
    results: list[RequestResult] = []

    client_kwargs: dict = {"base_url": base_url, "timeout": request_timeout}
    if transport is not None:
        client_kwargs["transport"] = transport

    start = time.monotonic()
    deadline = start + duration_seconds
    async with httpx.AsyncClient(**client_kwargs) as client:
        await asyncio.gather(
            *(_worker(i, client, scenarios, api_keys, deadline, rng, results) for i in range(concurrency))
        )
    elapsed_seconds = time.monotonic() - start

    return _build_report(results, elapsed_seconds)
