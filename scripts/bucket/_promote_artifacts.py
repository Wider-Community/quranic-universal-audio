"""Turn a staged generation run into the bytes ``promote_run.py`` publishes.

The fetch half of promote: verify ``staging/<slug>/<run-id>/`` and materialise it
locally. The build itself lives in ``inspector/services/segments/promote_build.py``
(shared with the native align pipeline) and is re-exported here so
``promote_run.py`` and its tests keep their ``pa.*`` surface.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "inspector"), str(Path(__file__).parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from qua_shared.schemas.bucket.staged_run import RunManifestDoc  # noqa: E402
from services.segments.promote_build import (  # noqa: E402, F401 — re-exported surface
    _PIPELINE_ACTOR,
    _SIDECARS,
    _jsonl_bytes,
    build_artifacts,
    build_chapter_peaks,
    build_meta,
    build_peaks_records,
    dumps,
    finalise_entries,
    meta_riwayah,
    read_entries,
    replay_events,
    stamp_waqf_uids,
)

STAGING_PREFIX = "staging"
MANIFEST_NAME = "manifest.json"


# ---------------------------------------------------------------------------
# Fetch and verify the staged run
# ---------------------------------------------------------------------------


def fetch_staged_run(backend, slug: str, run_id: str, dest: Path) -> RunManifestDoc:
    """Materialise ``staging/<slug>/<run-id>/`` under *dest*, verifying as it goes.

    Every declared artifact must be present with the manifest's size and digest,
    and every path in ``required`` must be declared. Raises before a single byte
    of ``reciters/<slug>/`` is touched — the inversion of "guess what should be
    here" into "everything declared is present and hashes match".
    """
    prefix = f"{STAGING_PREFIX}/{slug}/{run_id}"
    manifest = RunManifestDoc.model_validate(
        json.loads(backend.read_bytes(f"{prefix}/{MANIFEST_NAME}"))
    )
    if manifest.slug != slug:
        raise ValueError(f"manifest slug {manifest.slug!r} does not match {slug!r}")

    declared = {a.path for a in manifest.artifacts}
    undeclared = [p for p in manifest.required if p not in declared]
    if undeclared:
        raise ValueError(f"required paths absent from artifacts: {undeclared}")

    for entry in manifest.artifacts:
        try:
            data = backend.read_bytes(f"{prefix}/{entry.path}")
        except Exception as e:  # noqa: BLE001 — any read failure is the same abort
            raise ValueError(f"staged artifact unreadable: {entry.path} ({e})") from e
        if len(data) != entry.bytes:
            raise ValueError(f"{entry.path}: {len(data)} bytes, manifest says {entry.bytes}")
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry.sha256:
            raise ValueError(f"{entry.path}: sha256 {digest} != manifest {entry.sha256}")
        out = dest / entry.path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    return manifest
