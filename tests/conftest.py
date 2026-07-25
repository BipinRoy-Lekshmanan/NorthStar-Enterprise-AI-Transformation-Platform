"""Session-wide test isolation (Milestone 8).

`app.api.main.lifespan` builds a SQLite engine (for the operational
idempotency/audit/operations store) on every `TestClient(app)`
construction, reading `DATABASE_URL` via `DatabaseSettings.from_env()`.
Without an override, every test using `TestClient` would silently read
and write the real `data/app.db` -- this autouse fixture points every
test at its own `tmp_path` SQLite file instead, the same per-test
isolation already applied individually to `AUDIT_LOG_DIR`/
`WORKFLOW_STORE_DIR`/etc in existing test fixtures, but applied
globally here since `DATABASE_URL` is touched by *every* app-boot path,
not just the tests that exercise `app.db` directly.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolated_database_url(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
