"""I/O utilities: atomic writes + safe filenames.

v2: ``file_sha256`` and ``backup_file`` were retired. The file-hash chain
in ``edit_history.jsonl`` is gone (tamper detection via offsite bucket
versioned snapshots). Recovery of mis-saves is via the audit log + the
versioned bucket snapshots, not local ``.bak`` files.
"""

import os
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


def safe_filename(name: str, fallback: str = "file") -> str:
    """Strip characters unsafe in filenames, keeping alphanumerics and ``-_``.

    Returns *fallback* if the result would be empty.
    """
    cleaned = "".join(c for c in name if c.isalnum() or c in "-_").strip()
    return cleaned or fallback
