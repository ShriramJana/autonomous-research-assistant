"""Auth: Supabase JWT verification + FastAPI dependencies (built-in user in local mode)."""

from ara.auth.dependencies import (
    LOCAL_USER,
    get_current_user,
    get_optional_user,
    require_admin,
)
from ara.auth.jwt import User, verify_jwt

__all__ = [
    "LOCAL_USER",
    "User",
    "get_current_user",
    "get_optional_user",
    "require_admin",
    "verify_jwt",
]
