"""FastAPI dependencies that resolve the current Supabase user.

Token sources (checked in order):
1. ``Authorization: Bearer <jwt>`` header
2. Supabase auth cookie(s) written by ``@supabase/ssr``

The cookie path is what makes ``EventSource`` work — browsers can't add
custom headers to EventSource but they do send cookies on same-origin
requests, and the Next.js rewrites in ``next.config.ts`` make the
frontend and backend appear same-origin.

@supabase/ssr writes the session as a cookie (or several chunked cookies)
named ``sb-<project-ref>-auth-token`` (optionally suffixed ``.0``, ``.1``
to chunk values past the 4 KB cookie size limit). The concatenated value
is a base64-encoded JSON object of shape ``{access_token, refresh_token,
...}``. Modern @supabase/ssr emits raw base64; older releases prefix the
value with a literal ``base64-`` marker. We accept both.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, status

from ara.auth.jwt import User, verify_jwt
from ara.config import Settings, get_settings

_SB_COOKIE_RE = re.compile(r"^sb-[A-Za-z0-9_-]+-auth-token(?:\.(\d+))?$")
_BASE64_PREFIX = "base64-"


def _extract_cookie_token(cookies: dict[str, str]) -> str | None:
    """Reassemble the Supabase auth cookie(s) and return the access token.

    Supports both single-cookie and chunked-cookie (``...auth-token.0``,
    ``...auth-token.1``, ...) shapes, and both the legacy ``base64-`` prefix
    and the modern raw-base64 payloads.
    """
    chunks: list[tuple[int, str]] = []
    for name, value in cookies.items():
        match = _SB_COOKIE_RE.match(name)
        if match is None:
            continue
        index = int(match.group(1)) if match.group(1) is not None else 0
        chunks.append((index, value))
    if not chunks:
        return None

    chunks.sort(key=lambda pair: pair[0])
    raw = "".join(value for _, value in chunks)
    if raw.startswith(_BASE64_PREFIX):
        raw = raw[len(_BASE64_PREFIX) :]

    # urlsafe_b64decode tolerates both standard and URL-safe alphabets when
    # we normalise padding; some Supabase clients omit padding entirely.
    padding = "=" * (-len(raw) % 4)
    try:
        decoded = base64.urlsafe_b64decode(raw + padding)
    except (binascii.Error, ValueError):
        return None

    try:
        payload: Any = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        return None
    return token


def _extract_token(authorization: str | None, cookies: dict[str, str]) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return _extract_cookie_token(cookies)


def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> User:
    token = _extract_token(authorization, request.cookies)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return verify_jwt(token, settings)


def get_optional_user(
    request: Request,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> User | None:
    token = _extract_token(authorization, request.cookies)
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
