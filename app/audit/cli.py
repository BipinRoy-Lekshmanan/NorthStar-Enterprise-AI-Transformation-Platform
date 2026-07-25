"""`python -m app.audit verify` -- walks the hash chain and reports
whether the audit log is intact. Exit code 0 when valid, 1 when
tampering/corruption is detected, matching `python -m app.config
validate`'s exit-code convention.
"""

from __future__ import annotations

import argparse
import sys

from app.audit.store import AuditStore


def _run_verify() -> int:
    store = AuditStore.from_env()
    result = store.verify_chain()
    if result.valid:
        print(f"OK: audit chain intact ({result.total_events} event(s)).")
        return 0
    print(f"CORRUPTED: {result.reason}")
    print(f"First invalid sequence number: {result.first_invalid_sequence}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.audit", description="Audit log integrity tools.")
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("verify", help="Verify the audit log's hash chain is unbroken.")
    args = parser.parse_args(argv)

    if args.action == "verify":
        return _run_verify()
    return 1


if __name__ == "__main__":
    sys.exit(main())
