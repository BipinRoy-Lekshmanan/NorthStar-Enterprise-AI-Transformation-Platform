"""`python -m app.knowledge verify-index` (Milestone 8)."""

from __future__ import annotations

import argparse
import sys

from app.knowledge.verify import verify_index


def _run_verify_index() -> int:
    result = verify_index()
    print(f"Knowledge-base chunks: {result.knowledge_base_chunk_count}")
    print(f"Indexed chunks:        {result.indexed_chunk_count}")
    print(f"Missing from index:    {result.missing_from_index}")
    print(f"Stale in index:        {result.stale_in_index}")

    if result.healthy:
        print("OK: the vector index is healthy and in sync with the knowledge base.")
        return 0

    print("ISSUES FOUND:")
    for issue in result.issues:
        print(f"  - {issue}")
    if not result.corrupted:
        print("Run 'POST /knowledge/index' (incremental) or 'POST /operations/rebuild' (full) to resync.")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.knowledge", description="Knowledge-base index diagnostics.")
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser(
        "verify-index", help="Check the vector index for corruption and drift from the knowledge base.",
    )
    args = parser.parse_args(argv)

    if args.action == "verify-index":
        return _run_verify_index()
    return 1


if __name__ == "__main__":
    sys.exit(main())
