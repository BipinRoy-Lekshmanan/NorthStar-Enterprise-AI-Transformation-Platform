"""`python -m app.db upgrade|current|history` -- a thin wrapper over
Alembic's own command API, pointed at this repo's `alembic.ini` (whose
`script_location` is `app/db/migrations`). `env.py` reads the real
`DATABASE_URL` at run time via `DatabaseSettings`, so this CLI never
needs its own copy of that logic.
"""

from __future__ import annotations

import argparse
import sys

from alembic.config import Config

from app.config.settings import PROJECT_ROOT


def alembic_config() -> Config:
    return Config(str(PROJECT_ROOT / "alembic.ini"))


def main(argv: list[str] | None = None) -> int:
    from alembic import command

    parser = argparse.ArgumentParser(prog="python -m app.db", description="Operational database schema management.")
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("upgrade", help="Apply all pending migrations (upgrade to 'head').")
    subparsers.add_parser("current", help="Show the currently applied migration revision.")
    subparsers.add_parser("history", help="Show the full migration history.")
    args = parser.parse_args(argv)

    config = alembic_config()
    if args.action == "upgrade":
        command.upgrade(config, "head")
    elif args.action == "current":
        command.current(config, verbose=True)
    elif args.action == "history":
        command.history(config, verbose=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
