"""Staging the qua_sdk source the timestamps job imports, and the gate that
refuses a launch when the staged copy no longer matches what we stamp.

The SDK is not vendored in this repo and is not installable in the deployed
Space (it is a private workspace member), so it can only be staged from a
machine holding a checkout. Every other launch reuses the durable bucket copy.
That is fine while the copy is current and silently wrong once it is not: the
job then builds native documents with one contract and stamps another shard
version.

Three things close that gap. Staging MIRRORS the source tree — a file the SDK
dropped is deleted from the bucket, so the staged tree is the checkout rather
than the union of every checkout ever staged. It records the native shard
version and clean Git revision, which :func:`assert_staged_sdk` pairs against
the writer's pinned producer.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .base import ALIGNER_BUCKET, JobStagingError

#: Where the staged tree records what it is. Read at launch by every process,
#: including the ones that cannot stage.
MARKER_PATH = "code/qua_sdk_stage.json"

_SDK_PREFIX = "code/qua_sdk/"

#: The constant the SDK's native shard producer declares. Read from source rather
#: than imported: the staging host has the tree on disk but need not have it
#: importable.
_VERSION_RE = re.compile(r"^SHARD_SCHEMA_VERSION\s*=\s*(\d+)\s*$", re.MULTILINE)


def source_shard_version(sdk_src: Path) -> int:
    """The native shard version the SDK tree at ``sdk_src`` emits."""
    path = sdk_src / "integrations" / "shards.py"
    match = _VERSION_RE.search(path.read_text(encoding="utf-8")) if path.is_file() else None
    if match is None:
        raise JobStagingError(
            f"{path} declares no SHARD_SCHEMA_VERSION - the SDK checkout predates the "
            "staged-producer gate and cannot be staged"
        )
    return int(match.group(1))


def source_revision(sdk_src: Path) -> str:
    """Return the clean Git revision containing ``sdk_src``."""
    try:
        root = Path(
            subprocess.check_output(
                ["git", "-C", str(sdk_src), "rev-parse", "--show-toplevel"], text=True
            ).strip()
        )
        revision = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        relative = sdk_src.resolve().relative_to(root.resolve())
        dirty = subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain", "--", str(relative)], text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        raise JobStagingError(f"{sdk_src} is not inside a readable Git checkout") from exc
    if dirty:
        raise JobStagingError(f"qua_sdk source has uncommitted changes: {dirty.splitlines()[0]}")
    return revision


def stage_adds(sdk_src: Path) -> list[tuple[str, str]]:
    """``(local, bucket)`` pairs for the qua_sdk tree: ``*.py`` + ``py.typed`` +
    every packaged ``*.json`` data file, excluding ``__pycache__`` and the
    compiled ``_dp_core`` artefacts (the job uses timing only, never the DP
    core). The JSON sweep is tree-wide: the SDK carries data outside
    ``domain/data/`` (``components/matching/lib/reference/data/``, the
    integrations vocabularies), and a path-scoped filter silently ships a tree
    that import-errors at run time."""
    adds: list[tuple[str, str]] = []
    for path in sdk_src.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.name.startswith("_dp_core"):
            continue
        if not (path.suffix in (".py", ".json") or path.name == "py.typed"):
            continue
        rel = path.relative_to(sdk_src).as_posix()
        adds.append((str(path), f"{_SDK_PREFIX}{rel}"))
    return adds


def stale_targets(keep: set[str]) -> list[str]:
    """Staged SDK paths the source no longer carries.

    Without this the tree only ever grows: an add-only stage leaves a renamed
    or deleted module shadowing the current one on ``PYTHONPATH``.
    """
    from huggingface_hub import list_bucket_tree

    # The tree prefix matches as a string, not as a directory, so the sibling
    # marker at ``code/qua_sdk_stage.json`` comes back under ``code/qua_sdk``.
    # Deleting it would erase the very record the launch gate reads.
    staged = {
        entry.path
        for entry in list_bucket_tree(ALIGNER_BUCKET, _SDK_PREFIX.rstrip("/"), recursive=True)
        if getattr(entry, "size", None) is not None and entry.path.startswith(_SDK_PREFIX)
    }
    return sorted(staged - keep)


def marker_bytes(sdk_src: Path, n_files: int, expected_revision: str) -> bytes:
    revision = source_revision(sdk_src)
    if revision != expected_revision:
        raise JobStagingError(
            f"qua_sdk source revision is {revision}, expected {expected_revision}; "
            "stage the pinned checkout"
        )
    return json.dumps(
        {
            "shard_schema_version": source_shard_version(sdk_src),
            "source_revision": revision,
            "files": n_files,
        },
        indent=2,
    ).encode("utf-8")


def read_marker() -> dict | None:
    """The staged tree's marker, or None when it has never been written."""
    from huggingface_hub import hffs

    path = f"buckets/{ALIGNER_BUCKET}/{MARKER_PATH}"
    # The launcher is one long-lived worker and fsspec caches the miss. Without
    # this, a process that read the marker before a re-stage keeps reading the
    # absence it saw first, and the gate stays shut on a tree that is now fine.
    hffs.invalidate_cache(path)
    try:
        raw = hffs.cat_file(path)
    except Exception:  # noqa: BLE001 — absent marker reads as "unknown", not an error
        return None
    try:
        # cat_file is typed str | bytes; json.loads takes either, but only one
        # of them survives being handed to a reader expecting the other.
        marker = json.loads(raw)
    except ValueError:
        return None
    return marker if isinstance(marker, dict) else None


def assert_staged_sdk(expected: int, expected_revision: str) -> None:
    """Refuse a launch unless the staged producer matches the pinned contract.

    ``expected`` is the shard schema version this repo stamps. A launcher that
    could not stage the SDK still runs this, which is the whole point: it is
    the only signal such a process has that the bucket copy went stale.
    """
    marker = read_marker()
    if marker is None or marker.get("shard_schema_version") != expected:
        found = "none" if marker is None else marker.get("shard_schema_version")
        raise JobStagingError(
            f"the staged qua_sdk emits shard version {found}, but this repo stamps "
            f"schema {expected}. The deployed Space cannot stage the SDK (private "
            f"package, no checkout), so re-stage it from a machine that has one:\n"
            f"  QUA_SDK_SRC=<path>/packages/sdk/src/qua_sdk python -c "
            f"'from services.admin.timestamps_jobs import _stage_job_code; _stage_job_code()'"
        )
    if marker.get("source_revision") != expected_revision:
        found = marker.get("source_revision") or "none"
        raise JobStagingError(
            f"the staged qua_sdk revision is {found}, expected {expected_revision}; "
            "stage the pinned checkout before launching timestamps"
        )
