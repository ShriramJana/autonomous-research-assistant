"""Supabase JWT verification.

Supabase issues ES256-signed JWTs (ECC P-256) signed by a project-specific
private key. Public keys are published at
``{SUPABASE_URL}/auth/v1/.well-known/jwks.json`` and fetched via JWKS.

`PyJWKClient` caches keys internally; we additionally cache the client itself
per `supabase_url` so we don't construct a fresh HTTP client per request.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from uuid import UUID

import jwt as pyjwt
from fastapi import HTTPException, status
from jwt import PyJWKClient

from ara.config import Settings


@dataclass(frozen=True)
class User:
    id: UUID
    email: str


_JWKS_CLIENTS: dict[str, PyJWKClient] = {}
_JWKS_CLIENTS_LOCK = Lock()


def _jwks_url(supabase_url: str) -> str:
    return f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


def _get_jwks_client(supabase_url: str) -> PyJWKClient:
    """Return a process-wide cached ``PyJWKClient`` for the given Supabase URL.

    `PyJWKClient` itself caches keys; this just avoids re-creating the client
    (and its underlying HTTP session) on every request.
    """
    url = _jwks_url(supabase_url)
    client = _JWKS_CLIENTS.get(url)
    if client is not None:
        return client
    with _JWKS_CLIENTS_LOCK:
        client = _JWKS_CLIENTS.get(url)
        if client is None:
            client = PyJWKClient(url)
            _JWKS_CLIENTS[url] = client
    return client


def verify_jwt(token: str, settings: Settings) -> User:
    """Decode + validate a Supabase ES256 JWT against the project's JWKS.

    Raises HTTPException(401) on any failure — invalid signature, expired,
    missing sub/email, wrong audience, malformed token.
    Raises HTTPException(500) when Supabase URL is unconfigured.
    """
    if not settings.supabase_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication service unavailable",
        )
    try:
        jwks_client = _get_jwks_client(settings.supabase_url)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
            options={"require": ["exp", "sub", "email"]},
        )
    except pyjwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        ) from exc

    sub = payload["sub"]
    email = payload["email"]
    try:
        user_id = UUID(sub)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid sub claim"
        ) from exc
    return User(id=user_id, email=email)
