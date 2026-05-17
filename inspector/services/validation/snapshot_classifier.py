"""Classify a SegSnapshot dict (history record / op log shape).

A SegSnapshot is the loose dict shape persisted under
``edit_history.jsonl`` operation records (``targets_before``,
``targets_after``) and embedded in validation responses. It carries a
subset of segment fields — typically ``matched_ref``, ``confidence``,
``time_*``, ``segment_uid`` — without an enclosing entry or chapter
context.

This module derives whatever positional inputs the classifier needs from
the snapshot itself and routes through :func:`classify_segment`. No
classification logic is reimplemented here.
"""
from __future__ import annotations

from services.validation.classifier import classify_segment


def classify_snapshot(
    snap: dict,
    *,
    single_word_verses: set | None = None,
    canonical: dict | None = None,
    entry_ref: str = "",
    is_by_ayah: bool = False,
    probe_failed_uids: set | None = None,
) -> list[str]:
    """Classify a snapshot dict and return its category list.

    Position fields are derived from ``snap["matched_ref"]``. Snapshots
    typically don't carry an ``entry_ref`` (they predate by-ayah audio
    routing context), so ``audio_bleeding`` is unreachable from a bare
    snapshot — pass ``entry_ref`` and ``is_by_ayah=True`` when callers
    want the audio-bleeding signal too.

    ``probe_failed_uids`` mirrors the per-segment classifier kwarg —
    snapshots carry ``segment_uid``, so the *Low Confidence v2* category
    can resolve cleanly against the same sidecar uid set.

    Returns categories in registry-declared order.
    """
    if not snap or not isinstance(snap, dict):
        return []
    return classify_segment(
        snap,
        entry_ref=entry_ref or snap.get("entry_ref", ""),
        is_by_ayah=is_by_ayah,
        single_word_verses=single_word_verses,
        canonical=canonical,
        probe_failed_uids=probe_failed_uids,
    )


__all__ = ["classify_snapshot"]
