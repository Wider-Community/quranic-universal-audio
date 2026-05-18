"""Local-dev auto-mount helper for the HF inspector bucket.

`hf-mount` exposes the bucket as a FUSE filesystem at
``inspector/.bucket/{dev,prod}/`` (gitignored). When the mount is active,
the bucket backend reads files through it (~50-500× faster than
``hffs.cat_file``).

Both ``inspector/app.py`` (Flask boot) and stand-alone scripts like
``.local/extraction/list_pending_requests.py`` call ``auto_mount()`` so
they share the same mount semantics.

Failures degrade silently: if ``hf-mount`` isn't installed, the mount
already exists, the bucket is provided via ``INSPECTOR_BUCKET_MOUNT``, or
the subprocess fails, the caller still works through the API path.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Local mount root, relative to inspector/. Gitignored via inspector/.gitignore.
_INSPECTOR_DIR = Path(__file__).resolve().parent.parent.parent
_BUCKET_ROOT = _INSPECTOR_DIR / ".bucket"

# Where to look for the hf-mount binary when ``shutil.which`` misses it
# (common when CWD's PATH is minimal — e.g. systemd, cron, IDE terminals).
_HF_MOUNT_FALLBACKS = ("~/bin/hf-mount", "/usr/local/bin/hf-mount",
                       "/opt/homebrew/bin/hf-mount")

_DEFAULT_BUCKET = "hetchyy/quranic-inspector-bucket"


def _flavor_for(bucket: str) -> str:
    """``dev`` for repos suffixed ``-dev``, ``prod`` otherwise."""
    return "dev" if bucket.endswith("-dev") else "prod"


def mount_dir_for(bucket: str) -> Path:
    """Canonical mount path for *bucket* — useful for tests / scripts that
    want to inspect the FUSE tree directly."""
    return _BUCKET_ROOT / _flavor_for(bucket)


def _resolve_hf_mount() -> str | None:
    binary = shutil.which("hf-mount")
    if binary:
        return binary
    for cand in _HF_MOUNT_FALLBACKS:
        p = Path(cand).expanduser()
        if p.exists():
            return str(p)
    return None


def auto_mount(*, behind_proxy: bool | None = None,
               in_pytest: bool | None = None) -> Path | None:
    """Auto-mount the HF bucket and set ``INSPECTOR_BUCKET_MOUNT``.

    Returns the mount path on success, ``None`` if skipped or failed.

    Skipped when:
    * ``INSPECTOR_BEHIND_PROXY=1`` (deployed Space — mount already provided).
    * Running under pytest.
    * ``INSPECTOR_AUTO_MOUNT=0``.
    * ``INSPECTOR_BUCKET_MOUNT`` already set (caller pre-pinned a path).
    * ``INSPECTOR_BACKEND`` is set and not ``bucket``.
    * ``hf-mount`` binary isn't installed anywhere we look.
    """
    if behind_proxy is None:
        behind_proxy = os.environ.get("INSPECTOR_BEHIND_PROXY") == "1"
    if in_pytest is None:
        in_pytest = "pytest" in sys.modules
    if behind_proxy or in_pytest:
        return None
    if os.environ.get("INSPECTOR_AUTO_MOUNT") == "0":
        return None
    if os.environ.get("INSPECTOR_BUCKET_MOUNT"):
        return Path(os.environ["INSPECTOR_BUCKET_MOUNT"])
    if os.environ.get("INSPECTOR_BACKEND", "bucket").lower() != "bucket":
        return None

    hf_mount = _resolve_hf_mount()
    if not hf_mount:
        return None

    # `hf-mount` reads HF_TOKEN from env only — it doesn't pick up the
    # saved token at ~/.cache/huggingface/token. Backfill from disk so
    # scripts launched outside an .env-aware shell still mount.
    if not os.environ.get("HF_TOKEN"):
        saved = Path("~/.cache/huggingface/token").expanduser()
        if saved.is_file():
            try:
                token = saved.read_text(encoding="utf-8").strip()
                if token:
                    os.environ["HF_TOKEN"] = token
            except OSError:
                pass

    bucket = os.environ.get("INSPECTOR_BUCKET_REPO", _DEFAULT_BUCKET)
    mount_dir = mount_dir_for(bucket)
    mount_dir.mkdir(parents=True, exist_ok=True)

    def _activate() -> Path:
        os.environ["INSPECTOR_BUCKET_MOUNT"] = str(mount_dir)
        return mount_dir

    if os.path.ismount(str(mount_dir)):
        return _activate()

    try:
        result = subprocess.run(
            [hf_mount, "start", "--fuse", "--", "--advanced-writes",
             "bucket", bucket, str(mount_dir)],
            timeout=30, capture_output=True, text=True,
        )
    except Exception:  # noqa: BLE001
        return None

    for _ in range(50):
        if os.path.ismount(str(mount_dir)):
            return _activate()
        time.sleep(0.1)

    if result.returncode != 0:
        sys.stderr.write(
            f"[inspector] hf-mount auto-start failed (exit {result.returncode}): "
            f"{result.stderr.strip()[:200]}\n"
        )
    return None
