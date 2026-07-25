"""Engine/session construction for Milestone 8's operational SQLite store.

`build_engine()` is the single place a `DATABASE_URL` string becomes a
real SQLAlchemy `Engine` -- every caller (the FastAPI app, the CLI,
tests) goes through it, so the SQLite-specific `connect_args` (needed
because SQLite by default rejects use from more than one thread) is
never duplicated.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import DatabaseSettings
from app.db.models import Base


def build_engine(database_url: str | None = None) -> Engine:
    url = database_url or DatabaseSettings.from_env().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_all(engine: Engine) -> None:
    """Creates every table directly from the ORM metadata -- used by
    tests and by a fresh `sqlite:///:memory:` engine. Real deployments
    use Alembic migrations (`python -m app.db upgrade`) instead, so
    schema history is tracked."""
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Commits on a clean exit, rolls back and re-raises on any
    exception -- the one place transaction boundaries are decided, so
    callers never need to remember to commit/rollback themselves."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
