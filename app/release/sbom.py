"""SBOM generation (Milestone 8).

Shells out to `cyclonedx-bom`'s own CLI (`python -m cyclonedx_py
environment`) rather than calling its Python API directly -- the same
reasoning `app.db.cli` wraps Alembic's `command` module instead of its
internal migration machinery: the CLI surface is the stable contract,
not whatever internal classes a dependency happens to expose.

Generates from the *installed environment* (not `requirements.txt`
directly) so every component gets a real, exact version -- this
repo's `requirements.txt` is range-pinned (`fastapi>=0.110`), which
would otherwise show up in the SBOM as "no pinned version" for every
single package.
"""

from __future__ import annotations

import subprocess  # nosec B404 -- only used with a fixed argv below, no shell, no user input
import sys
from pathlib import Path


class SbomGenerationError(Exception):
    """Raised when the underlying `cyclonedx-py` command fails."""


def generate_sbom(output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(  # nosec B603 -- fixed argv, no shell, no user input
        [sys.executable, "-m", "cyclonedx_py", "environment", "--of", "json", "-o", str(output_path)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SbomGenerationError(f"cyclonedx-py exited with code {result.returncode}: {result.stderr.strip()}")
    return output_path
