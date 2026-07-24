"""Authentication endpoints (Milestone 7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.auth.users import User

router = APIRouter()


@router.get("/auth/me", summary="Get the current authenticated user", tags=["Auth"])
def get_me(user: User = Depends(get_current_user)) -> User:
    """Resolves the caller's `X-API-Key` header into their username and
    role. Returns 401 if the header is missing or unrecognized."""
    return user
