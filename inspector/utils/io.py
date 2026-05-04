"""I/O utilities: atomic writes, hashing, backups."""

import hashlib
import json
import os
import shutil
from pathlib import Path


import orjson

def atomic_json_write(path: Path, data, *, ensure_ascii: bool = False) -> None:
    """Write *data* to *path* as JSON via a temp file + atomic rename.

    This avoids partial reads if the server crashes mid-write.
    """
    tmp_path = path.with_suffix(".json.tmp")
    with open(tmp_path, "wb") as f:
        # orjson defaults to UTF-8 without ASCII escaping.
        f.write(orjson.dumps(data))
    os.replace(tmp_path, path)


def file_sha256(path: Path) -> str:
    """Return ``"sha256:<hex>"`` digest of file at *path*."""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def backup_file(path: Path) -> None:
    """Create a ``.bak`` copy of *path* if it exists."""
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))


def safe_filename(name: str, fallback: str = "file") -> str:
    """Strip characters unsafe in filenames, keeping alphanumerics and ``-_``.

    Returns *fallback* if the result would be empty.
    """
    cleaned = "".join(c for c in name if c.isalnum() or c in "-_").strip()
    return cleaned or fallback
