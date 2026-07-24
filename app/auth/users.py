"""Local, config-based user directory (Milestone 7).

A flat JSON file mapping API keys to a username + role, loaded once at
API startup into an in-memory dict for O(1) per-request lookup. Not
production-grade authentication -- no password hashing, no token
expiry, no identity federation. Real deployments should replace this
entire module with a real identity provider; see the root README's
"Production deployment considerations" section.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from app.auth.roles import Role


class User(BaseModel):
    username: str
    role: Role
    api_key: str = Field(exclude=True)  # never serialized into an API response


class UserDirectoryError(Exception):
    """Raised when the users file is missing, empty, or malformed."""


def load_users(path: Path) -> dict[str, User]:
    """Load `path` (a JSON list of `{api_key, username, role}` objects)
    into a dict keyed by `api_key`."""
    if not path.exists():
        raise UserDirectoryError(
            f"Users file not found at '{path}'. Copy data/auth/users.example.json "
            "to this path and adjust it, or set AUTH_USERS_FILE to point elsewhere."
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise UserDirectoryError(f"Users file at '{path}' is not valid JSON: {exc}") from exc

    users: dict[str, User] = {}
    for entry in raw:
        try:
            user = User.model_validate(entry)
        except Exception as exc:
            raise UserDirectoryError(f"Invalid user entry in '{path}': {entry!r} ({exc})") from exc
        if user.api_key in users:
            raise UserDirectoryError(f"Duplicate api_key in '{path}' for user '{user.username}'.")
        users[user.api_key] = user

    if not users:
        raise UserDirectoryError(f"Users file at '{path}' contains no users.")

    return users
