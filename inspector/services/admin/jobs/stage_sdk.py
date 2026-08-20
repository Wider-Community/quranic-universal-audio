"""Staging the qua_sdk source the timestamps job imports, and the gate that
refuses a launch when the staged copy no longer matches what we stamp.

The SDK is not vendored in this repo and is not installable in the deployed
Space (it is a private workspace member), so it can only be staged from a
machine holding a checkout. Every other launch reuses the durable bucket copy.
That is fine while the copy is current and silently wrong once it is not: the
job then builds cell rows with one producer and stamps them with another
version's number, and writes a shard neither side can read.

Two things close that gap. Staging MIRRORS the source tree — a file the SDK
dropped is deleted from the bucket, so the staged tree is the checkout rather
than the union of every checkout ever staged. And it records the cell-row
version the staged producer emits, which :func:`assert_staged_sdk` pairs
against the schema version the shard writer stamps.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .base import ALIGNER_BUCKET, JobStagingError

#: Where the staged tree records what it is. Read at launch by every process,
#: including the ones that cannot stage.
MARKER_PATH = "code/qua_sdk_stage.json"

_SDK_PREFIX = "code/qua_sdk/"

#: The constant the SDK's cell-row producer declares. Read from source rather
#: than imported: the staging host has the tree on disk but need not have it
#: importable.
_VERSION_RE = re.compile(r"^CELL_ROW_VERSION\s*=\s*(\d+)\s*$", re.MULTILINE)


def source_cell_row_version(sdk_src: Path) -> int:
    """The cell-row version the SDK tree at ``sdk_src`` emits."""
    path = sdk_src / "integrations" / "cellrows.py"
    match = _VERSION_RE.search(path.read_text(encoding="utf-8")) if path.is_file() else None
    if match is None:
        raise JobStagingError(
            f"{path} declares no CELL_ROW_VERSION — the SDK checkout predates the "
            "staged-producer gate and cannot be staged"
        )
    return int(match.group(1))


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


def marker_bytes(sdk_src: Path, n_files: int) -> bytes:
    return json.dumps(
        {"cell_row_version": source_cell_row_version(sdk_src), "files": n_files},
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


def assert_staged_sdk(expected: int) -> None:
    """Refuse the launch unless the staged producer emits ``expected`` rows.

    ``expected`` is the shard schema version this repo stamps. A launcher that
    could not stage the SDK still runs this, which is the whole point: it is
    the only signal such a process has that the bucket copy went stale.
    """
    marker = read_marker()
    if marker is None or marker.get("cell_row_version") != expected:
        found = "none" if marker is None else marker.get("cell_row_version")
        raise JobStagingError(
            f"the staged qua_sdk emits cell-row version {found}, but this repo stamps "
            f"schema {expected}. The deployed Space cannot stage the SDK (private "
            f"package, no checkout), so re-stage it from a machine that has one:\n"
            f"  QUA_SDK_SRC=<path>/packages/sdk/src/qua_sdk python -c "
            f"'from services.admin.timestamps_jobs import _stage_job_code; _stage_job_code()'"
        )
