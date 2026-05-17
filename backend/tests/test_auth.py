"""JWT verification + FastAPI auth dependencies."""

from __future__ import annotations

import time
from uuid import UUID, uuid4

import jwt as pyjwt
import pytest
from fastapi import HTTPException

from ara.auth.dependencies import get_optional_user, require_admin
from ara.auth.jwt import User, verify_jwt
from ara.config import Settings

_SECRET = "test-secret-min-32-chars-for-supabase-hs256-jwt-verify"


def _make_token(
    *,
    sub: UUID | None = None,
    email: str = "user@example.com",
    secret: str = _SECRET,
    aud: str = "authenticated",
    expires_in: int = 3600,
    alg: str = "HS256",
) -> str:
    now = int(time.time())
    payload = {
        "sub": str(sub or uuid4()),
        "email": email,
        "aud": aud,
        "iat": now,
        "exp": now + expires_in,
    }
    return pyjwt.encode(payload, secret, algorithm=alg)


def _settings(secret: str = _SECRET) -> Settings:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    s.supabase_jwt_secret = secret
    return s


def test_verify_jwt_happy_path() -> None:
    uid = uuid4()
    token = _make_token(sub=uid, email="alice@example.com")
    user = verify_jwt(token, _settings())
    assert isinstance(user, User)
    assert user.id == uid
    assert user.email == "alice@example.com"


def test_verify_jwt_rejects_wrong_signature() -> None:
    token = _make_token(secret="different-secret-also-32-chars-long-here-ok")
    with pytest.raises(HTTPException) as exc:
        verify_jwt(token, _settings())
    assert exc.value.status_code == 401


def test_verify_jwt_rejects_expired() -> None:
    token = _make_token(expires_in=-60)
    with pytest.raises(HTTPException) as exc:
        verify_jwt(token, _settings())
    assert exc.value.status_code == 401


def test_verify_jwt_rejects_wrong_audience() -> None:
    token = _make_token(aud="some-other-audience")
    with pytest.raises(HTTPException) as exc:
        verify_jwt(token, _settings())
    assert exc.value.status_code == 401


def test_verify_jwt_rejects_missing_sub() -> None:
    now = int(time.time())
    token = pyjwt.encode(
        {"email": "x@x.com", "aud": "authenticated", "exp": now + 3600},
        _SECRET,
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc:
        verify_jwt(token, _settings())
    assert exc.value.status_code == 401


def test_verify_jwt_rejects_garbage() -> None:
    with pytest.raises(HTTPException) as exc:
        verify_jwt("not-a-jwt", _settings())
    assert exc.value.status_code == 401


def test_verify_jwt_500s_when_secret_unset() -> None:
    token = _make_token()
    with pytest.raises(HTTPException) as exc:
        verify_jwt(token, _settings(secret=""))
    assert exc.value.status_code == 500


def test_verify_jwt_rejects_non_uuid_sub() -> None:
    now = int(time.time())
    token = pyjwt.encode(
        {"sub": "not-a-uuid", "email": "x@x.com", "aud": "authenticated", "exp": now + 3600},
        _SECRET,
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc:
        verify_jwt(token, _settings())
    assert exc.value.status_code == 401


def test_get_optional_user_returns_none_on_bad_token() -> None:
    user = get_optional_user(
        authorization="Bearer not-a-jwt",
        sb_access_token=None,
        settings=_settings(),
    )
    assert user is None


def test_get_optional_user_returns_user_on_good_token() -> None:
    uid = uuid4()
    token = _make_token(sub=uid)
    user = get_optional_user(
        authorization=f"Bearer {token}",
        sb_access_token=None,
        settings=_settings(),
    )
    assert user is not None
    assert user.id == uid


def test_get_optional_user_propagates_500() -> None:
    """A misconfigured server should NOT be silently treated as unauthenticated."""
    token = _make_token()
    with pytest.raises(HTTPException) as exc:
        get_optional_user(
            authorization=f"Bearer {token}",
            sb_access_token=None,
            settings=_settings(secret=""),
        )
    assert exc.value.status_code == 500


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
