"""Helpers for building ``pipeline_meta.json`` content.

Single source of truth for the derivation logic shared by:

- ``scripts/backfill_deleted_basmala.py`` — derives the field for legacy
  reciters from ``edit_history.jsonl``.
- ``.local/extraction/segments/post_passes.py`` / ``outputs.py`` — writes
  the sidecar directly during extraction (exact set, no derivation).
- Tests — exercise the same logic.

Schema: ``qua_shared/schemas/pipeline_meta.py::PipelineMeta``.
"""

from __future__ import annotations

from typing import Iterable


# The aligner's combined "Isti'adha+Basmala" ref is treated as a Basmala
# deletion. New extractions normalise the snapshot ref to "Basmala" via
# ``.local/extraction/segments/post_passes.py::_BASMALA_EQUIVALENT_REFS``,
# but tolerating the combined form is cheap and covers legacy data.
_BASMALA_DELETION_REFS = ("Basmala", "Isti'adha+Basmala")


def collect_deleted_basmalas(batches: Iterable[dict]) -> set[int]:
    """Return the set of chapters whose Basmala the pipeline stripped.

    Walks ``strip_specials`` batches in ``edit_history.jsonl`` (already
    parsed into dicts) and collects ``snap.chapter`` for each delete-op
    snapshot whose ``matched_ref`` is a Basmala (or the combined
    Isti'adha+Basmala) marker.

    Migration #5 contract: every strip_specials snapshot carries a
    ``chapter`` stamp. The pre-#5 4-tier fallback (heuristic recovery
    from time-reset groups, union over ``batch.chapters``, etc.) has been
    deleted from inspector and is NOT reintroduced here — run
    ``migrate_wip5_in_place.py`` on any reciter whose snapshots lack the
    stamp before backfilling.

    Deterministic: re-running on unchanged history produces a byte-equal
    set (used by the backfill drift check).
    """
    out: set[int] = set()
    for batch in batches:
        if batch.get("batch_type") != "strip_specials":
            continue
        for op in batch.get("operations") or []:
            snaps = op.get("targets_before") or []
            if not snaps or not isinstance(snaps[0], dict):
                continue
            snap = snaps[0]
            if snap.get("matched_ref") not in _BASMALA_DELETION_REFS:
                continue
            ch = snap.get("chapter")
            if isinstance(ch, int) and ch > 0:
                out.add(ch)
    return out
