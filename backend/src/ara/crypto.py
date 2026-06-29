"""App-level symmetric encryption for stored provider credentials.

Fernet (AES-128-CBC + HMAC) with a server-held key from `ARA_ENCRYPTION_KEY`.
Ciphertext is stored in Supabase; plaintext keys never leave the backend.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class CredentialDecryptError(Exception):
    """Stored ciphertext could not be decrypted (tampered or wrong/rotated key)."""


def generate_key() -> str:
    """Return a fresh urlsafe-base64 Fernet key (for ops / tests)."""
    return Fernet.generate_key().decode("ascii")


def encrypt_secret(plaintext: str, *, key: str) -> str:
    token = Fernet(key.encode("ascii")).encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_secret(token: str, *, key: str) -> str:
    try:
        return Fernet(key.encode("ascii")).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise CredentialDecryptError(str(exc)) from exc
