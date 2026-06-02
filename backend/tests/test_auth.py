"""JWT verification + FastAPI auth dependencies (ES256 + JWKS)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.types import (
    CertificatePublicKeyTypes,
    PublicKeyTypes,
)
from fastapi import HTTPException

from ara.auth import jwt as auth_jwt
from ara.auth.dependencies import get_optional_user, require_admin
from ara.auth.jwt import User, verify_jwt
from ara.config import Settings

_SUPABASE_URL = "https://example.supabase.co"


@pytest.fixture(autouse=True)
def _clear_jwks_client_cache() -> Iterator[None]:
    """Ensure tests don't share a stale (mocked) PyJWKClient across runs."""
    auth_jwt._JWKS_CLIENTS.clear()
    yield
    auth_jwt._JWKS_CLIENTS.clear()


@pytest.fixture(scope="module")
def signing_keypair() -> tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


@pytest.fixture(scope="module")
def other_keypair() -> tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey]:
    """A separate keypair used to test wrong-signature rejection."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


def _make_token(
    private_key: ec.EllipticCurvePrivateKey,
    *,
    sub: UUID | str | None = None,
    include_sub: bool = True,
    email: str | None = "user@example.com",
    aud: str = "authenticated",
    expires_in: int = 3600,
    alg: str = "ES256",
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "aud": aud,
        "iat": now,
        "exp": now + expires_in,
    }
    if include_sub:
        payload["sub"] = str(sub) if sub is not None else str(uuid4())
    if email is not None:
        payload["email"] = email
    return pyjwt.encode(payload, private_key, algorithm=alg)


def _settings(url: str = _SUPABASE_URL) -> Settings:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    s.supabase_url = url
    return s


class _FakeSigningKey:
    def __init__(self, key: PublicKeyTypes | CertificatePublicKeyTypes) -> None:
        self.key = key


def _patch_signing_key(public_key: ec.EllipticCurvePublicKey) -> Any:
    """Patch PyJWKClient.get_signing_key_from_jwt to return our test public key."""
    return patch(
        "ara.auth.jwt.PyJWKClient.get_signing_key_from_jwt",
        return_value=_FakeSigningKey(public_key),
    )


# --- verify_jwt --------------------------------------------------------------


def test_verify_jwt_happy_path(
    signing_keypair: tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey],
) -> None:
    private, public = signing_keypair
    uid = uuid4()
    token = _make_token(private, sub=uid, email="alice@example.com")
    with _patch_signing_key(public):
        user = verify_jwt(token, _settings())
    assert isinstance(user, User)
    assert user.id == uid
    assert user.email == "alice@example.com"


def test_verify_jwt_rejects_wrong_signature(
    signing_keypair: tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey],
    other_keypair: tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey],
) -> None:
    """Token signed by a different private key — JWKS public key won't verify it."""
    _, public = signing_keypair
    other_private, _ = other_keypair
    token = _make_token(other_private)
    with _patch_signing_key(public), pytest.raises(HTTPException) as exc:
        verify_jwt(token, _settings())
    assert exc.value.status_code == 401


def test_verify_jwt_rejects_expired(
    signing_keypair: tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey],
) -> None:
    private, public = signing_keypair
    token = _make_token(private, expires_in=-60)
    with _patch_signing_key(public), pytest.raises(HTTPException) as exc:
        verify_jwt(token, _settings())
    assert exc.value.status_code == 401


def test_verify_jwt_rejects_wrong_audience(
    signing_keypair: tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey],
) -> None:
    private, public = signing_keypair
    token = _make_token(private, aud="some-other-audience")
    with _patch_signing_key(public), pytest.raises(HTTPException) as exc:
        verify_jwt(token, _settings())
    assert exc.value.status_code == 401


def test_verify_jwt_rejects_missing_sub(
    signing_keypair: tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey],
) -> None:
    private, public = signing_keypair
    token = _make_token(private, include_sub=False)
    with _patch_signing_key(public), pytest.raises(HTTPException) as exc:
        verify_jwt(token, _settings())
    assert exc.value.status_code == 401


def test_verify_jwt_rejects_missing_email(
    signing_keypair: tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey],
) -> None:
    private, public = signing_keypair
    token = _make_token(private, email=None)
    with _patch_signing_key(public), pytest.raises(HTTPException) as exc:
        verify_jwt(token, _settings())
    assert exc.value.status_code == 401


def test_verify_jwt_rejects_garbage(
    signing_keypair: tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey],
) -> None:
    _, public = signing_keypair
    # PyJWKClient.get_signing_key_from_jwt may itself raise on garbage; the
    # verifier maps any PyJWTError to 401.
    with _patch_signing_key(public), pytest.raises(HTTPException) as exc:
        verify_jwt("not-a-jwt", _settings())
    assert exc.value.status_code == 401


def test_verify_jwt_500s_when_url_unset(
    signing_keypair: tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey],
) -> None:
    private, _ = signing_keypair
    token = _make_token(private)
    with pytest.raises(HTTPException) as exc:
        verify_jwt(token, _settings(url=""))
    assert exc.value.status_code == 500


def test_verify_jwt_rejects_non_uuid_sub(
    signing_keypair: tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey],
) -> None:
    private, public = signing_keypair
    token = _make_token(private, sub="not-a-uuid")
    with _patch_signing_key(public), pytest.raises(HTTPException) as exc:
        verify_jwt(token, _settings())
    assert exc.value.status_code == 401


# --- get_optional_user -------------------------------------------------------


def test_get_optional_user_returns_none_on_bad_token(
    signing_keypair: tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey],
) -> None:
    _, public = signing_keypair
    with _patch_signing_key(public):
        user = get_optional_user(
            authorization="Bearer not-a-jwt",
            sb_access_token=None,
            settings=_settings(),
        )
    assert user is None


def test_get_optional_user_returns_user_on_good_token(
    signing_keypair: tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey],
) -> None:
    private, public = signing_keypair
    uid = uuid4()
    token = _make_token(private, sub=uid)
    with _patch_signing_key(public):
        user = get_optional_user(
            authorization=f"Bearer {token}",
            sb_access_token=None,
            settings=_settings(),
        )
    assert user is not None
    assert user.id == uid


def test_get_optional_user_propagates_500(
    signing_keypair: tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey],
) -> None:
    """A misconfigured server should NOT be silently treated as unauthenticated."""
    private, _ = signing_keypair
    token = _make_token(private)
    with pytest.raises(HTTPException) as exc:
        get_optional_user(
            authorization=f"Bearer {token}",
            sb_access_token=None,
            settings=_settings(url=""),
        )
    assert exc.value.status_code == 500


# --- require_admin -----------------------------------------------------------


def test_require_admin_allows_admin() -> None:
    admin_id = uuid4()
    s = _settings()
    s.admin_user_id = str(admin_id)
    user = User(id=admin_id, email="admin@x.com")
    assert require_admin(user=user, settings=s) is user


def test_require_admin_denies_non_admin() -> None:
    s = _settings()
    s.admin_user_id = str(uuid4())  # some other user
    user = User(id=uuid4(), email="rando@x.com")
    with pytest.raises(HTTPException) as exc:
        require_admin(user=user, settings=s)
    assert exc.value.status_code == 403


def test_require_admin_denies_when_admin_id_unset() -> None:
    s = _settings()
    s.admin_user_id = None
    user = User(id=uuid4(), email="anyone@x.com")
    with pytest.raises(HTTPException) as exc:
        require_admin(user=user, settings=s)
    assert exc.value.status_code == 403


# --- JWKS client caching -----------------------------------------------------


def test_jwks_client_is_cached_per_url() -> None:
    a1 = auth_jwt._get_jwks_client(_SUPABASE_URL)
    a2 = auth_jwt._get_jwks_client(_SUPABASE_URL)
    assert a1 is a2
    b = auth_jwt._get_jwks_client("https://other.supabase.co")
    assert b is not a1
