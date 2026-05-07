"""Segment patch domain object.

``SegmentPatch`` describes the changes produced by a single command.  The
backend's undo path uses it to apply the inverse transformation against the
current in-memory entries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SegmentPatch:
    """Describes the forward change produced by a command.

    ``before`` and ``after`` are full segment-dict snapshots keyed by the
    order they appear in the command.  ``removedIds`` and ``insertedIds``
    carry the segment UIDs that were removed or inserted by this command
    (non-overlapping with ``before``/``after`` uid sets for trim/ignore/ref
    edits, but overlap deliberately for split/merge).
    ``affectedChapterIds`` is the set of chapter numbers whose id ordering
    changed (used by the frontend to rewrite ``idsByChapter``).
    """

    before: tuple[dict, ...]
    after: tuple[dict, ...]
    removedIds: tuple[str, ...]
    insertedIds: tuple[str, ...]
    affectedChapterIds: tuple[int, ...]


def patch_from_dict(d: dict) -> SegmentPatch:
    """Construct a ``SegmentPatch`` from the raw JSON dict carried in an op."""
    return SegmentPatch(
        before=tuple(d.get("before") or []),
        after=tuple(d.get("after") or []),
        removedIds=tuple(d.get("removedIds") or []),
        insertedIds=tuple(d.get("insertedIds") or []),
        affectedChapterIds=tuple(int(c) for c in (d.get("affectedChapterIds") or [])),
    )


def _REQUIRED_PATCH_KEYS() -> frozenset[str]:
    return frozenset({"before", "after", "removedIds", "insertedIds", "affectedChapterIds"})


def validate_patch_dict(d: Any) -> str | None:
    """Return an error message if *d* is not a well-formed patch dict, else None."""
    if not isinstance(d, dict):
        return "patch must be a JSON object"
    missing = _REQUIRED_PATCH_KEYS() - d.keys()
    if missing:
        return f"patch missing required fields: {sorted(missing)}"
    if not isinstance(d.get("before"), list):
        return "patch.before must be a list"
    if not isinstance(d.get("after"), list):
        return "patch.after must be a list"
    if not isinstance(d.get("removedIds"), list):
        return "patch.removedIds must be a list"
    if not isinstance(d.get("insertedIds"), list):
        return "patch.insertedIds must be a list"
    if not isinstance(d.get("affectedChapterIds"), list):
        return "patch.affectedChapterIds must be a list"
    return None


def apply_inverse_patch(entries: list[dict], patch: dict) -> list[dict]:
    """Apply the inverse of *patch* to *entries* and return the mutated list.

    The inverse transformation:
    1. Remove segments whose ``segment_uid`` appears in ``insertedIds``.
    2. Restore the ``before`` snapshot for each uid that appears in ``before``
       (matched by ``segment_uid``).
    3. Re-insert the ``before`` snapshots for uids in ``removedIds``
       (these were deleted by the forward command; inverse re-adds them).

    The entries list is mutated in place and returned for convenience.
    """
    patch_obj = patch_from_dict(patch)

    # Index before-snapshots by uid for O(1) lookup.
    before_by_uid: dict[str, dict] = {
        s["segment_uid"]: s
        for s in patch_obj.before
        if isinstance(s, dict) and s.get("segment_uid")
    }

    # 1. Remove inserted ids (they were created by the forward command).
    inserted_set = set(patch_obj.insertedIds)
    for entry in entries:
        segs = entry.get("segments", [])
        entry["segments"] = [s for s in segs if s.get("segment_uid") not in inserted_set]

    # 2. Restore before-snapshots for segments that still exist
    #    (trim / editReference / ignoreIssue — same uid, different field values).
    removed_set = set(patch_obj.removedIds)
    for entry in entries:
        for i, seg in enumerate(entry.get("segments", [])):
            uid = seg.get("segment_uid")
            if uid and uid in before_by_uid and uid not in removed_set:
                entry["segments"][i] = dict(before_by_uid[uid])

    # 3. Re-insert segments that the forward command removed.
    #    We need to find the right entry to insert into; we match by the
    #    ``audio_url`` carried in the before-snapshot, with a chapter-based
    #    fallback when the snapshot pre-dates the audio_url field.
    for uid in patch_obj.removedIds:
        snap = before_by_uid.get(uid)
        if not snap:
            continue
        audio_url = snap.get("audio_url", "")
        target_entry = _find_entry_for_restore(entries, snap, patch_obj.affectedChapterIds, audio_url)
        if target_entry is not None:
            target_entry["segments"].append(dict(snap))

    # 4. Re-insert any before-segments that are still absent from entries.
    #    This handles the case where a full_replace save with empty segments
    #    cleared segments that the op only mutated in-place (e.g., ignore_issue
    #    or trim). The inverse patch should restore those segments.
    present_after_steps_1_3: set[str] = set()
    for entry in entries:
        for seg in entry.get("segments", []):
            uid = seg.get("segment_uid")
            if uid:
                present_after_steps_1_3.add(uid)

    for uid, snap in before_by_uid.items():
        if uid not in present_after_steps_1_3:
            audio_url = snap.get("audio_url", "")
            target_entry = _find_entry_for_restore(
                entries, snap, patch_obj.affectedChapterIds, audio_url
            )
            if target_entry is not None:
                target_entry["segments"].append(dict(snap))

    # Sort segments in each affected entry by time_start to maintain order.
    affected_refs = _refs_for_chapters(entries, patch_obj.affectedChapterIds)
    for entry in entries:
        if entry.get("ref") in affected_refs or not affected_refs:
            segs = entry.get("segments", [])
            segs.sort(key=lambda s: s.get("time_start", 0))

    return entries


# ---------------------------------------------------------------------------
# Private helpers for apply_inverse_patch
# ---------------------------------------------------------------------------

def _refs_for_chapters(entries: list[dict], chapter_ids: tuple[int, ...]) -> set[str]:
    """Return the set of entry refs that match any of *chapter_ids*."""
    if not chapter_ids:
        return set()
    result: set[str] = set()
    for entry in entries:
        ref = entry.get("ref", "")
        try:
            from utils.references import chapter_from_ref  # type: ignore
            ch = chapter_from_ref(ref)
        except Exception:
            try:
                ch = int(ref.split(":")[0]) if ":" in ref else int(ref)
            except Exception:
                continue
        if ch in chapter_ids:
            result.add(ref)
    return result


def _find_entry_for_restore(
    entries: list[dict],
    snap: dict,
    chapter_ids: tuple[int, ...],
    audio_url: str,
) -> dict | None:
    """Find the entry to re-insert a restored segment into.

    Prefers audio_url match; falls back to first entry whose chapter is in
    *chapter_ids*.
    """
    # Pass 1: exact audio_url match.
    if audio_url:
        for entry in entries:
            if entry.get("audio", "") == audio_url:
                return entry

    # Pass 2: first entry whose chapter is in the affected set.
    for entry in entries:
        ref = entry.get("ref", "")
        try:
            from utils.references import chapter_from_ref  # type: ignore
            ch = chapter_from_ref(ref)
        except Exception:
            try:
                ch = int(ref.split(":")[0]) if ":" in ref else int(ref)
            except Exception:
                continue
        if ch in chapter_ids:
            return entry

    # Pass 3: any entry at all (last resort).
    return entries[0] if entries else None
