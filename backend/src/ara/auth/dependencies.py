"""FastAPI dependencies that resolve the current Supabase user.

Token sources (checked in order):
1. `Authorization: Bearer <jwt>` header
2. `sb-access-token` cookie (set by @supabase/ssr on the frontend)

The cookie path is what makes `EventSource` work — browsers can't add
custom headers to EventSource but they do send cookies on same-origin
requests, and the Next.js rewrites in `next.config.ts` make the
frontend and backend appear same-origin.
"""

from __future__ import annotations

from fastapi import Cookie, Depends, Header, HTTPException, status

from ara.auth.jwt import User, verify_jwt
from ara.config import Settings, get_settings


def _extract_token(authorization: str | None, sb_access_token: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    if sb_access_token:
        return sb_access_token
    return None


def get_current_user(
    authorization: str | None = Header(default=None),
    sb_access_token: str | None = Cookie(default=None, alias="sb-access-token"),
    settings: Settings = Depends(get_settings),
) -> User:
    token = _extract_token(authorization, sb_access_token)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return verify_jwt(token, settings)


def get_optional_user(
    authorization: str | None = Header(default=None),
    sb_access_token: str | None = Cookie(default=None, alias="sb-access-token"),
    settings: Settings = Depends(get_settings),
) -> User | None:
    token = _extract_token(authorization, sb_access_token)
    if token is None:
        return None
    try:
        return verify_jwt(token, settings)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            return None
        raise


def require_admin(
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> User:
    if settings.admin_user_id is None or str(user.id) != settings.admin_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user
