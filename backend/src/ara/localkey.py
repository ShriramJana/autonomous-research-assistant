"""Local-mode encryption key: generated once, stored beside the database."""

from __future__ import annotations

import os
from pathlib import Path

from ara.crypto import generate_key

KEY_FILENAME = "encryption.key"


def load_or_create_key(data_dir: str) -> str:
    path = Path(data_dir) / KEY_FILENAME
    try:
        if path.exists():
            return path.read_text().strip()
        path.parent.mkdir(parents=True, exist_ok=True)
        key = generate_key()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(key)
        return key
    except OSError as exc:
        raise RuntimeError(
            f"Cannot read or create {path} (set ARA_DATA_DIR to a writable folder): {exc}"
        ) from exc
