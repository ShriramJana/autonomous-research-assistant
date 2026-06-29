from __future__ import annotations

import pytest

from ara.crypto import (
    CredentialDecryptError,
    decrypt_secret,
    encrypt_secret,
    generate_key,
)

KEY = "BaZLQFEp7N_J26mxi0P8g4cRridnZ0mjERLdNyqYV1A="  # a valid 32-byte urlsafe-b64 Fernet key


def test_round_trip() -> None:
    token = encrypt_secret("sk-secret-123", key=KEY)
    assert token != "sk-secret-123"
    assert decrypt_secret(token, key=KEY) == "sk-secret-123"


def test_decrypt_tampered_raises() -> None:
    token = encrypt_secret("x", key=KEY)
    # Flip a character in the middle to corrupt the HMAC
    mid = len(token) // 2
    bad_char = "A" if token[mid] != "A" else "B"
    tampered = token[:mid] + bad_char + token[mid + 1 :]
    with pytest.raises(CredentialDecryptError):
        decrypt_secret(tampered, key=KEY)


def test_decrypt_wrong_key_raises() -> None:
    token = encrypt_secret("x", key=KEY)
    other = generate_key()
    with pytest.raises(CredentialDecryptError):
        decrypt_secret(token, key=other)


def test_generate_key_is_usable() -> None:
    k = generate_key()
    assert decrypt_secret(encrypt_secret("y", key=k), key=k) == "y"
