"""`python -m app.release validate|sbom` (Milestone 8)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config.settings import ConfigurationError
from app.release.sbom import SbomGenerationError, generate_sbom
from app.release.validate import validate_release


def _run_validate() -> int:
    try:
        result = validate_release()
    except ConfigurationError as exc:
        print(f"NOT_READY: configuration error -- {exc}")
        return 1

    if not result.problems:
        print(f"READY: release checks passed for environment '{result.environment.value}'.")
        return 0

    if result.environment.is_production_like:
        print(
            f"NOT_READY: {len(result.problems)} release-blocking issue(s) "
            f"for environment '{result.environment.value}':"
        )
        for problem in result.problems:
            print(f"  - {problem}")
        return 1

    print(
        f"READY_WITH_WARNINGS: release checks pass for environment '{result.environment.value}', "
        f"but {len(result.problems)} issue(s) would block a release in staging/production:"
    )
    for problem in result.problems:
        print(f"  - {problem}")
    return 0


def _run_sbom(args: argparse.Namespace) -> int:
    try:
        path = generate_sbom(Path(args.output))
    except SbomGenerationError as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"SBOM written to {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.release", description="Release readiness checks + SBOM generation.",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    subparsers.add_parser("validate", help="Check release readiness; exits non-zero if blocked.")

    sbom_parser = subparsers.add_parser("sbom", help="Generate a CycloneDX SBOM for the current environment.")
    sbom_parser.add_argument("--output", default="sbom.json", help="Output file path (default: sbom.json).")

    args = parser.parse_args(argv)
    if args.action == "validate":
        return _run_validate()
    return _run_sbom(args)


if __name__ == "__main__":
    sys.exit(main())
