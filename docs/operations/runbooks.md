# Runbooks

Routine operational procedures, each a real command against this
repository's actual CLIs — every command below was run at least once
during Milestone 8's own end-to-end validation. See
`incident-playbooks.md` for what to do when something is actually
wrong, and `deployment-architecture.md` for how the pieces fit
together.

## Starting the platform

**Local (no containers):**

```bash
python -m app.api                    # terminal 1 -- FastAPI on :8000
streamlit run app/frontend/main.py   # terminal 2 -- Streamlit on :8501
```

**Local (containers):**

```bash
docker compose up --build
```

Before either: `python -m app.config validate` — confirms
configuration loads and reports any warnings (default credentials,
disallowed models) before you rely on the process staying up.

## Checking whether the platform is healthy

```bash
curl -s http://localhost:8000/api/v1/health          # liveness -- process is up
curl -s http://localhost:8000/api/v1/health/ready     # readiness -- 503 if a real dependency check fails
curl -s http://localhost:8000/api/v1/platform/info -H "x-api-key: <admin-or-viewer-key>"
curl -s http://localhost:8000/metrics | head -50       # real Prometheus exposition text
```

`/health/ready` is what a Kubernetes readiness probe (`04-api.yaml`)
and the Docker `HEALTHCHECK` both key off; it's deliberately
unauthenticated since an orchestrator's probe can't send credentials.

## Checking release readiness before a deploy

```bash
python -m app.release validate
```

Prints `READY`, `READY_WITH_WARNINGS`, or `NOT_READY` (exit 1) for the
*current* environment's env vars. Run this against the target
environment's real configuration (not your local shell) before
promoting a build — it catches default/example credentials outside
local/dev/test, disallowed model overrides, an `APP_VERSION`/
`pyproject.toml` version mismatch, and a database schema behind the
code's expected Alembic HEAD.

```bash
python -m app.db current                 # what revision is the DB actually at?
python -m app.db upgrade                 # apply pending migrations
```

## Generating a Software Bill of Materials

```bash
python -m app.release sbom --output sbom.json
```

CycloneDX JSON from the *installed* environment (real exact package
versions, not the range-pinned `requirements.txt`). Regenerate after
any dependency change intended for a release.

## Backup and restore

```bash
python -m app.operations backup --destination backups/$(date +%Y%m%d)
python -m app.operations restore --archive backups/20260101.zip --force   # --force to overwrite an existing target
```

One `.zip`: the SQLite operational database (via SQLite's own backup
API, safe against a concurrently open live server — verified live in
Milestone 8), the vector store, the workflow store, and evaluation-run
history. Deliberately **excludes** the knowledge-base source documents
(tracked in git already) and the users file (credentials never belong
in a shared backup archive). After restoring, confirm audit integrity:

```bash
python -m app.audit verify
```

## Retention cleanup

```bash
python -m app.operations cleanup --dry-run     # always review before the real run
python -m app.operations cleanup
```

Age-based (mtime) cleanup of old backups and expired idempotency
records. `--dry-run` is the default posture to reach for first.

## Verifying the knowledge index

```bash
python -m app.knowledge verify-index
```

Read-only comparison of the vector store's indexed chunk IDs against
what a fresh ingestion run would produce today — reports missing/
stale/corrupted entries without changing anything. Follow with a real
rebuild if it reports drift:

```bash
curl -s -X POST http://localhost:8000/api/v1/operations/rebuild \
  -H "x-api-key: <administrator-key>" -H "Content-Type: application/json" \
  -d '{"confirmation": "REBUILD"}'
curl -s http://localhost:8000/api/v1/operations -H "x-api-key: <administrator-key>"   # poll for completion
```

Rebuild runs on a background thread (`202 Accepted` immediately);
poll `GET /operations` or `GET /operations/{id}` for status. If
`FEATURE_FLAGS=background_operations=false` is set, this endpoint
returns `404` — use the synchronous `POST /knowledge/rebuild` (same
`{"confirmation": "REBUILD"}` body) instead.

## Rotating API keys

1. Edit the real `data/auth/users.json` (git-ignored; never the
   committed `users.example.json`) — add the new key, mark the old one
   `"enabled": false` rather than deleting it outright if you need an
   audit trail of who had access when.
2. Restart the API process (the user directory is loaded once at
   lifespan startup).
3. Confirm: `curl -s .../api/v1/auth/me -H "x-api-key: <new-key>"`
   returns 200; the old key now returns 401 indistinguishably from an
   unrecognized key (never a different error for "disabled" vs.
   "never existed" — see `app/auth/dependencies.py`).
4. Before doing this in staging/production,
   `python -m app.release validate` will flag if any *remaining* key
   still matches a default/example marker.

## Checking usage and cost

```bash
curl -s http://localhost:8000/api/v1/platform/usage -H "x-api-key: <viewer-or-above-key>"
```

Today's spend (UTC calendar day) and remaining budget if
`DAILY_BUDGET_USD` is configured. A `fake`-provider deployment (the
default) always reports zero cost — there's no real bill to estimate.

## Reviewing the audit trail

```bash
curl -s "http://localhost:8000/api/v1/platform/audit?limit=50" -H "x-api-key: <administrator-key>"
python -m app.audit verify        # hash-chain integrity check
```

Every significant action (question asked, workflow executed/approved,
ingestion/index/rebuild run, evaluation triggered, a rate-limit
rejection) is here with actor, role, action, resource, and outcome —
never full prompts, answers, or secrets.

## Running a load test

```bash
python -m app.loadtest run \
  --base-url http://localhost:8000 --duration 30 --concurrency 10 \
  --api-key <key-1> --api-key <key-2> --output report.json
```

Multiple `--api-key` values are round-robined across workers — each
key gets its own rate-limit bucket (`(actor, category)`), so more keys
sustain more real throughput before hitting `429`s. A `429` in the
report is the rate limiter working as designed, not a failure; check
the printed note for that context.

## Aggregate configuration and capacity check

```bash
python -m app.config show --redacted   # fully resolved settings, secrets masked
python -m app.config limits            # every configured limit across every settings class, in one snapshot
```
