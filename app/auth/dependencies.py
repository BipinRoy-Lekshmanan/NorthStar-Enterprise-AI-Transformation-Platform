"""FastAPI dependencies resolving the current user and enforcing role
requirements (Milestone 7).

`get_current_user` is the single place that turns an `X-API-Key` header
into a `User` -- it raises a 401 `ApiError` when the header is missing
or unrecognized. `require_role` composes on top of it via `Depends`, so
a 403 is only ever raised once a user has already been successfully
resolved -- the 401-vs-403 split falls out of dependency ordering, not
conditional logic.
"""

from __future__ import annotations

from fastapi import Depends, Header, Request

from app.api.errors import ApiError, ErrorCode
from app.auth.roles import Role, role_at_least
from app.auth.users import User

API_KEY_HEADER = "X-API-Key"


def get_current_user(
    request: Request, x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER)
) -> User:
    if not x_api_key:
        raise ApiError(401, ErrorCode.UNAUTHORIZED, "Missing X-API-Key header.")

    users: dict[str, User] = request.app.state.users
    user = users.get(x_api_key)
    if user is None:
        raise ApiError(401, ErrorCode.UNAUTHORIZED, "Invalid API key.")

    return user


def require_role(minimum: Role):
    """Dependency factory: `Depends(require_role(Role.REVIEWER))`."""

    def _check(user: User = Depends(get_current_user)) -> User:
        if not role_at_least(user.role, minimum):
            raise ApiError(
                403,
                ErrorCode.FORBIDDEN,
                f"This action requires the '{minimum.value}' role or higher; you have '{user.role.value}'.",
                details={"required_role": minimum.value, "actual_role": user.role.value},
            )
        return user

    return _check
