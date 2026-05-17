"""Supabase JWT verification.

Supabase issues HS256-signed JWTs by default using the project's
`JWT_SECRET`. Verification is purely local — no network call.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import jwt as pyjwt
from fastapi import HTTPException, status

from ara.config import Settings


@dataclass(frozen=True)
class User:
    id: UUID
    email: str


def verify_jwt(token: str, settings: Settings) -> User:
    """Decode + validate a Supabase JWT.

    Raises HTTPException(401) on any failure — invalid signature,
    expired, missing sub/email, wrong audience, malformed token.
    """
    if not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfigured: SUPABASE_JWT_SECRET not set",
        )
    try:
        payload = pyjwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except pyjwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}"
        ) from exc

    sub = payload.get("sub")
    email = payload.get("email")
    if not sub or not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing required claims (sub, email)",
        )
    try:
        user_id = UUID(sub)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid sub claim"
        ) from exc
    return User(id=user_id, email=email)
