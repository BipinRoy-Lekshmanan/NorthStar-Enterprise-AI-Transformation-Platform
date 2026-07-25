# Dashboards

Four Grafana-importable dashboard JSON files, grounded in the real
collectors defined in `app/telemetry/metrics.py` (every PromQL `expr`
in these files references a metric that actually exists -- verified by
diffing the two against each other, not written aspirationally).

| File | Covers |
|---|---|
| `platform-health.json` | API availability, request volume, p95 latency, error rate, provider failures, vector-store status proxy |
| `ai-quality.json` | Sufficient-context rate, citation presence, routing confidence/fallback rate, evaluation pass rate, provider failures |
| `workflow-operations.json` | Active/awaiting-approval executions, completion rate, per-stage duration, findings by severity, approval wait time |
| `knowledge-operations.json` | Indexed document/chunk counts, ingestion failures, indexing duration, time since last successful run |

## Prerequisites

1. A Prometheus instance scraping the platform's `GET /metrics`
   endpoint (see the `observability` profile in `docker-compose.yml`
   and `docs/operations/prometheus.yml`).
2. A Grafana instance with that Prometheus instance added as a
   datasource.

## Import

Grafana UI -> Dashboards -> New -> Import -> upload the JSON file (or
paste its contents) -> select the Prometheus datasource -> Import.

These are **not** auto-provisioned by `docker-compose.yml` -- the
`observability` profile only starts Prometheus + (optionally) an
OpenTelemetry collector, matching the milestone's own "avoid adding
technologies solely to make the architecture appear more complex"
guidance. Import manually, or provision them yourself via Grafana's
[dashboard provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/#dashboards)
if you stand up Grafana as part of your own deployment.
