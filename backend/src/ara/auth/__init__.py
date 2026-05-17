"""Auth: Supabase JWT verification + FastAPI dependencies."""

from ara.auth.dependencies import (
    get_current_user,
    get_optional_user,
    require_admin,
)
from ara.auth.jwt import User, verify_jwt

__all__ = [
    "User",
    "get_current_user",
    "get_optional_user",
    "require_admin",
    "verify_jwt",
]
