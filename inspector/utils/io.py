"""I/O utilities: atomic writes, hashing, backups."""

import hashlib
import json
import os
import shutil
from pathlib import Path


def atomic_json_write(path: Path, data, *, ensure_ascii: bool = False) -> None:
    """Write *data* to *path* as JSON via a temp file + atomic rename.

    This avoids partial reads if the server crashes mid-write.
    """
    tmp_path = path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=ensure_ascii)
    os.replace(tmp_path, path)


def file_sha256(path: Path) -> str:
    """Return ``"sha256:<hex>"`` digest of file at *path*."""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def backup_file(path: Path) -> None:
    """Create a ``.bak`` copy of *path* if it exists."""
    if path.exists():
        shutil.copy2(path, path.with_suffix(".json.bak"))
