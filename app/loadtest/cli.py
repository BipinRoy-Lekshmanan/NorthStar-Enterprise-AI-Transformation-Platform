"""`python -m app.loadtest run` (Milestone 8)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.loadtest.harness import LoadTestReport, run_load_test


def format_report(report: LoadTestReport) -> str:
    lines = [
        f"Duration: {report.duration_seconds:.1f}s   Total requests: {report.total_requests}   "
        f"Throughput: {report.requests_per_second:.1f} req/s   Errors (connection/5xx): {report.total_errors}",
        "",
        f"{'scenario':<16}{'count':>8}{'p50 ms':>10}{'p95 ms':>10}{'p99 ms':>10}   status codes",
    ]
    for name, stats in sorted(report.by_scenario.items()):
        pct = stats.percentiles()
        codes = ", ".join(f"{code}:{count}" for code, count in sorted(stats.status_codes.items()))
        lines.append(
            f"{name:<16}{stats.count:>8}{pct['p50']:>10.1f}{pct['p95']:>10.1f}{pct['p99']:>10.1f}   {codes}"
        )

    if any(429 in stats.status_codes for stats in report.by_scenario.values()):
        lines.append("")
        lines.append(
            "Note: 429 responses are the per-category rate limiter "
            "(app.api.middleware.rate_limit) working as designed under load, "
            "not a failure. Pass more --api-key values (round-robined across "
            "workers), or raise RATE_LIMIT_*_PER_MINUTE, to sustain higher "
            "per-actor throughput."
        )

    return "\n".join(lines)


def _report_to_dict(report: LoadTestReport) -> dict:
    return {
        "duration_seconds": report.duration_seconds,
        "total_requests": report.total_requests,
        "total_errors": report.total_errors,
        "requests_per_second": report.requests_per_second,
        "by_scenario": {
            name: {
                "count": stats.count,
                "errors": stats.errors,
                "status_codes": stats.status_codes,
                "percentiles": stats.percentiles(),
            }
            for name, stats in report.by_scenario.items()
        },
    }


def _run_run(args: argparse.Namespace) -> int:
    report = asyncio.run(
        run_load_test(
            base_url=args.base_url,
            api_keys=args.api_keys,
            duration_seconds=args.duration,
            concurrency=args.concurrency,
            request_timeout=args.timeout,
        )
    )
    print(format_report(report))

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(_report_to_dict(report), f, indent=2)
        print(f"\nFull report written to {args.output}")

    if report.total_requests == 0:
        print("ERROR: no requests completed -- is the target reachable?")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.loadtest", description="Hand-rolled async load-test harness for the Northstar API.",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    run_parser = subparsers.add_parser("run", help="Run a load test against a live API instance.")
    run_parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Target API base URL.")
    run_parser.add_argument("--duration", type=float, default=20.0, help="Duration in seconds (default: 20).")
    run_parser.add_argument("--concurrency", type=int, default=10, help="Concurrent workers (default: 10).")
    run_parser.add_argument(
        "--api-key", dest="api_keys", action="append", default=[],
        help="API key to authenticate as; repeatable, round-robined across workers.",
    )
    run_parser.add_argument("--timeout", type=float, default=10.0, help="Per-request timeout in seconds.")
    run_parser.add_argument("--output", default=None, help="Optional path to write the full report as JSON.")

    args = parser.parse_args(argv)
    return _run_run(args)


if __name__ == "__main__":
    sys.exit(main())
