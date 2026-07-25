# Incident playbooks

What to do when something is actually wrong. Each playbook: how to
recognize it, what's really happening under the hood, and the concrete
commands to confirm and respond. See `runbooks.md` for routine
(non-incident) procedures and `deployment-architecture.md` for the
single-process components referenced below.

## 1. Grounded answers are degraded / provider errors spiking

**Symptom**: `POST /query` returns `200` but with a warning about
retrieval-only mode, or clients report slow/failing answers.

**What's happening**: `OpenAIModelProvider`/`OpenAIEmbeddingProvider`
wrap every call in retry-with-backoff + a circuit breaker
(`app/resilience/circuit_breaker.py`). After 5 failures (the default
`failure_threshold`) the breaker opens and every subsequent call fails
fast for 30 seconds (`reset_timeout_seconds`) without attempting the
real provider at all —
`app.api.services.query_service` catches that and falls back to
retrieval-only excerpts with a warning rather than a hard 502 or a
fabricated answer.

**Confirm:**

```bash
curl -s http://localhost:8000/metrics | grep -E "circuit_breaker_state|provider_failures_total|provider_retries_total"
```

`circuit_breaker_state{provider="openai_llm"} 1` means open right now
(`0`=closed, `2`=half-open). Check `provider_failures_total`'s
`error_type` label for *why* — `ModelRateLimitError` and
`ModelTimeoutError` are the provider's own signal, not this
platform's bug.

**Respond:**

- If the underlying provider (OpenAI) is having a real outage: nothing
  to do but wait — the breaker will self-test (half-open) after the
  reset timeout and close again once the provider recovers. The
  degraded response is the correct, designed behavior, not a bug.
- If failures are `ModelConfigurationError` (bad API key, unsupported
  model): this is **not** retried or circuit-broken by design (a
  config problem doesn't get better by retrying) — fix `LLM_API_KEY`/
  `LLM_MODEL` and restart.
- Remember: this is a **single-process** breaker (see
  `deployment-architecture.md`'s multi-instance caveat) — with more
  than one API replica, each tracks failures independently.

## 2. Clients getting 429s unexpectedly

**Symptom**: `429` responses with `{"error": {"code": "RATE_LIMITED", ...}}`.

**What's happening**: `RateLimitMiddleware` enforces a per-`(actor,
category)` sliding 60-second window (`app/api/middleware/rate_limit.py`).
`actor` is the caller's API key (or client IP with none); `category`
is derived from the URL prefix (`query`, `advisor`, `workflow`,
`evaluation`, `administration`, else `default`).

**Confirm:**

```bash
curl -s "http://localhost:8000/api/v1/platform/audit?limit=20" -H "x-api-key: <administrator-key>" \
  | python -c "import json,sys; [print(e) for e in json.load(sys.stdin) if e['action']=='rate_limit_exceeded']"
curl -s http://localhost:8000/metrics | grep rate_limit_rejections_total
```

Every rejection is both audited (`action=rate_limit_exceeded`,
`resource_id=<category>`) and counted per category.

**Respond:**

- Legitimate high-volume caller: give it its own API key (each key is
  its own rate-limit bucket) rather than raising the global limit.
- Genuinely needs more headroom: raise
  `API_RATE_LIMIT_PER_MINUTE`/`RATE_LIMIT_<CATEGORY>_PER_MINUTE` and
  restart — this is a single-process, in-memory limiter (see
  `deployment-architecture.md`), so the effective limit already
  multiplies by replica count; account for that before raising it
  further.
- The response already includes a `Retry-After` header — well-behaved
  clients should back off to that, not retry immediately.

## 3. A background operation (rebuild) appears stuck

**Symptom**: `GET /operations/{id}` stays `"status": "running"` far
longer than expected.

**Confirm:**

```bash
curl -s http://localhost:8000/api/v1/operations/<id> -H "x-api-key: <viewer-or-above-key>"
```

Check the API process's own logs for exceptions during ingestion — a
failure inside the background thread is recorded on the operation
record itself (`status: "failed"`, an `error` field), not silently
swallowed.

**Respond:**

- If genuinely hung (large KB, slow disk): this is expected to take
  proportionally longer than a normal ingestion; there is no
  cancel-in-place for a running background operation in this
  milestone — restarting the API process is the only way to abort it.
  A second rebuild attempt while one is in-flight is rejected
  immediately with a clear conflict (`LockRegistry`,
  `app/resilience/concurrency.py`) rather than silently queuing behind it.
- After restart, run `python -m app.knowledge verify-index` to check
  whether the index is now consistent or needs a fresh rebuild.

## 4. Duplicate side effects from client retries

**Symptom**: a client that retried a request (network blip, timeout)
appears to have triggered the same workflow/ingestion/index run twice.

**What's happening**: if the client sent an `Idempotency-Key` header,
it shouldn't have — `check_idempotency()`
(`app/resilience/idempotency.py`) returns the original cached response
for a repeated `(endpoint, key)` pair without re-running anything.

**Confirm:**

```bash
python -c "
import sqlite3
con = sqlite3.connect('data/app.db')
print(con.execute(\"select endpoint, count(*) from idempotency_records group by endpoint\").fetchall())
"
```

If the client did **not** send `Idempotency-Key`, this is expected
behavior, not a bug — idempotency is opt-in per request, not automatic
for every write.

**Respond:**

- Confirm the client sends a stable, unique `Idempotency-Key` per
  logical operation (not a new UUID per retry attempt, which defeats
  the purpose).
- Idempotency records expire (see `python -m app.operations cleanup`)
  — a retry long after the original key expired will run again, by
  design, not as a bug.

## 5. Suspected audit log tampering or corruption

**Symptom**: any reason to doubt the audit trail's integrity (a
suspicious gap, an external report of unauthorized DB access).

**Confirm:**

```bash
python -m app.audit verify
```

Walks every event in sequence, re-deriving each `current_hash` from
`(sequence_number, previous_hash, timestamp, actor, role, action,
resource_type, resource_id, request_id, outcome, metadata,
organization_id)` and comparing. Any mismatch or gap in
`sequence_number` is reported explicitly with the offending event.

**Respond:**

- `OK`: chain is intact — no further action.
- A reported mismatch: treat as a real security incident, not a
  transient glitch — the whole point of hash-chaining is that this
  should never happen from ordinary operation. Preserve the current
  `data/app.db` (copy it aside before any further writes) and a
  `python -m app.operations backup` for forensics before investigating
  further.

## 6. Database schema drift after a deployment

**Symptom**: the API fails to start, or `python -m app.release
validate` reports a schema-migration-state problem.

**Confirm:**

```bash
python -m app.db current                # actual applied revision
python -m app.release validate          # flags a mismatch against the code's expected HEAD
```

**Respond:**

```bash
python -m app.operations backup --destination backups/pre-migration    # always back up first
python -m app.db upgrade
python -m app.release validate          # confirm the schema issue is gone
```

## 7. Suspected default/example credentials in a real environment

**Symptom**: `python -m app.release validate` (or `app.config
validate`) reports default/example credential markers
(`change-me`/`example-key`) — blocking in staging/production, a
warning in local/development/test.

**Confirm:**

```bash
python -m app.release validate
```

**Respond:**

- Replace `AUTH_USERS_FILE`'s content with real, rotated keys (see
  `runbooks.md`'s "Rotating API keys") — never edit the committed
  `data/auth/users.example.json` itself; point `AUTH_USERS_FILE` at a
  separate, git-ignored file.
- Re-run `python -m app.release validate` until it reports `READY`
  with no credential warning before considering the environment
  production-ready.
