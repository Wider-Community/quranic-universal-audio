"""Compute whether a reciter's generated timestamps are behind its segments.

The generated timestamps go stale the moment a timestamp-affecting segment edit
(trim/split/merge/delete/edit_reference/auto_fix_missing_word — see
``qua_shared.segment_edit_ops``) is saved after the last TS generation. This is
*computed* at read time — never stamped — so it stays accurate as edits land and
auto-clears when a regeneration moves ``produced_at`` past every edit. Keeping it
out of the save path leaves the segments editor (the hottest write path)
SQLite-free.

Surfaced on the Releases-tab TS chip via ``routes/admin/releases.py``; the
matching per-reciter history "tier" view lives in ``history_tiers.py``.
"""

from __future__ import annotations

from qua_shared.segment_edit_ops import batch_affects_timestamps
from services.activity import history_query


def ts_stale_info(slug: str, *, produced_at: str) -> dict | None:
    """Return staleness for ``slug``'s generated timestamps, or ``None``.

    ``produced_at`` is the current ``per_recitation_releases(track='ts')`` row's
    generation time (ISO-8601 UTC). Walks the reciter's edit-history batches and
    collects those saved after it that carry a timestamp-affecting op. Returns
    ``{"stale_since": <earliest such saved_at_utc>, "edits_since": <count>}`` when
    any exist, else ``None`` (nothing generated, or only annotation edits since).
    """
    stale_since: str | None = None
    count = 0
    for batch in history_query.parse_history_for_reciter(slug):
        saved_at = batch.get("saved_at_utc")
        if not saved_at or saved_at <= produced_at:
            continue
        if not batch_affects_timestamps(batch):
            continue
        count += 1
        if stale_since is None or saved_at < stale_since:
            stale_since = saved_at
    if count == 0:
        return None
    return {"stale_since": stale_since, "edits_since": count}
