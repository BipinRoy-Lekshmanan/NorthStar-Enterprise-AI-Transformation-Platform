"""Role-based access control primitives (Milestone 7).

Four hierarchical roles -- each higher role inherits every permission of
the roles below it (administrator > reviewer > engineer > viewer). This
is deliberately a simple ordinal hierarchy, not a per-permission ACL
system: every route in this milestone needs "at least this role," never
an arbitrary combination of unrelated permissions, so one ordering is
sufficient and far easier to audit than a permissions matrix.

This is a portfolio reference implementation of local RBAC, not
production-grade identity -- see `app.auth.users` and the root README's
"Production deployment considerations" section.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    VIEWER = "viewer"
    ENGINEER = "engineer"
    REVIEWER = "reviewer"
    ADMINISTRATOR = "administrator"


_ROLE_ORDER: dict[Role, int] = {
    Role.VIEWER: 0,
    Role.ENGINEER: 1,
    Role.REVIEWER: 2,
    Role.ADMINISTRATOR: 3,
}


def role_at_least(actual: Role, minimum: Role) -> bool:
    """True if `actual` has at least as much authority as `minimum`."""
    return _ROLE_ORDER[actual] >= _ROLE_ORDER[minimum]
