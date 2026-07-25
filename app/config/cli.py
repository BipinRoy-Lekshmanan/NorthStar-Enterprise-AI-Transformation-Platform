"""Configuration diagnostics CLI (Milestone 8).

    python -m app.config validate
    python -m app.config show --redacted
    python -m app.config limits

Pure formatting/exit-code logic only -- `production_checks.py` and each
settings class's own `.validate()` hold every actual rule.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from enum import Enum
from pathlib import Path
from typing import Any

from app.config.limits import CapacityLimits
from app.config.production_checks import SettingsBundle, load_all_settings, validate_production_readiness
from app.config.redaction import redact
from app.config.settings import ConfigurationError


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: _json_safe(getattr(value, field.name)) for field in dataclasses.fields(value)}
    return value


def _bundle_to_redacted_dict(bundle: SettingsBundle) -> dict:
    raw = _json_safe(bundle)
    return redact(raw)


def _run_validate() -> int:
    try:
        bundle = load_all_settings()
    except ConfigurationError as exc:
        print(f"NOT_READY: configuration error -- {exc}")
        return 1

    problems = validate_production_readiness(bundle)

    if not problems:
        print(f"READY: configuration is valid for environment '{bundle.environment.value}'.")
        return 0

    if bundle.environment.is_production_like:
        print(f"NOT_READY: {len(problems)} production-readiness issue(s) for environment '{bundle.environment.value}':")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(
        f"READY_WITH_WARNINGS: configuration is valid for environment '{bundle.environment.value}', "
        f"but {len(problems)} issue(s) would fail in staging/production:"
    )
    for problem in problems:
        print(f"  - {problem}")
    return 0


def _run_show() -> int:
    try:
        bundle = load_all_settings()
    except ConfigurationError as exc:
        print(f"Configuration error -- {exc}")
        return 1

    print(json.dumps(_bundle_to_redacted_dict(bundle), indent=2))
    return 0


def _run_limits() -> int:
    try:
        bundle = load_all_settings()
    except ConfigurationError as exc:
        print(f"Configuration error -- {exc}")
        return 1

    limits = CapacityLimits.from_settings_bundle(bundle)
    print(json.dumps(_json_safe(limits), indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Northstar platform configuration diagnostics.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate", help="Validate configuration; exits non-zero if unsafe/incomplete.")

    show_parser = subparsers.add_parser("show", help="Print effective configuration.")
    show_parser.add_argument(
        "--redacted", action="store_true", default=True,
        help="Redact secret-shaped fields (always on -- this command never prints raw secrets).",
    )

    subparsers.add_parser("limits", help="Print the consolidated capacity-limit view.")

    args = parser.parse_args()

    if args.command == "validate":
        raise SystemExit(_run_validate())
    if args.command == "show":
        raise SystemExit(_run_show())
    if args.command == "limits":
        raise SystemExit(_run_limits())


if __name__ == "__main__":
    main()
