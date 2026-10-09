from pathlib import Path

import pytest

from ara.crypto import decrypt_secret, encrypt_secret
from ara.localkey import load_or_create_key


def test_creates_key_once_and_reuses_it(tmp_path: Path) -> None:
    first = load_or_create_key(str(tmp_path))
    second = load_or_create_key(str(tmp_path))
    assert first == second
    assert decrypt_secret(encrypt_secret("s", key=first), key=first) == "s"
    assert (tmp_path / "encryption.key").stat().st_mode & 0o777 == 0o600


def test_unwritable_dir_raises_clear_error(tmp_path: Path) -> None:
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        with pytest.raises(RuntimeError, match=r"encryption\.key"):
            load_or_create_key(str(ro))
    finally:
        ro.chmod(0o700)
