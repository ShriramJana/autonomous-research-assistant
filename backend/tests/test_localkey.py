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


def test_empty_key_file_is_regenerated(tmp_path: Path) -> None:
    (tmp_path / "encryption.key").write_text("  \n")
    key = load_or_create_key(str(tmp_path))
    assert decrypt_secret(encrypt_secret("s", key=key), key=key) == "s"
    assert (tmp_path / "encryption.key").read_text().strip() == key
    assert (tmp_path / "encryption.key").stat().st_mode & 0o777 == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["encryption.key"]


def test_garbage_key_file_raises_and_is_left_alone(tmp_path: Path) -> None:
    (tmp_path / "encryption.key").write_text("not-a-fernet-key")
    with pytest.raises(RuntimeError, match=r"encryption\.key"):
        load_or_create_key(str(tmp_path))
    assert (tmp_path / "encryption.key").read_text() == "not-a-fernet-key"


def test_creates_owner_only_data_dir(tmp_path: Path) -> None:
    data_dir = tmp_path / "fresh"
    load_or_create_key(str(data_dir))
    assert data_dir.stat().st_mode & 0o777 == 0o700
