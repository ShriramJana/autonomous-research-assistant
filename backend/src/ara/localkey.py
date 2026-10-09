"""Local-mode encryption key: generated once, stored beside the database."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

from ara.crypto import generate_key

KEY_FILENAME = "encryption.key"


def load_or_create_key(data_dir: str) -> str:
    path = Path(data_dir) / KEY_FILENAME
    try:
        if path.exists():
            existing = path.read_text().strip()
            if existing:
                try:
                    Fernet(existing.encode())
                except ValueError as exc:
                    raise RuntimeError(
                        f"{path} does not contain a valid encryption key. Do not delete it "
                        "blindly: saved credentials may be encrypted with it. Restore it "
                        "from a backup, or remove it only if you accept re-saving your keys."
                    ) from exc
                return existing
            # Empty/whitespace: nothing can depend on it; fall through and regenerate.
        path.parent.mkdir(parents=True, exist_ok=True)
        key = generate_key()
        # Write a temp file in the same dir (mkstemp is 0600), then atomically
        # replace, so a half-written key file never exists.
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".encryption-key-")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(key)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return key
    except OSError as exc:
        raise RuntimeError(
            f"Cannot read or create {path} (set ARA_DATA_DIR to a writable folder): {exc}"
        ) from exc
