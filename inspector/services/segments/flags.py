"""Flag-thread serialization for the Segments editor read path.

A persisted ``SegmentFlag`` carries a full ``actor`` (``hf_user_id`` /
``login_at_time`` / ``role``) on the root comment and every follow-up. This
module reduces it to the FE-facing shape, redacting author identity to the
**role only** for viewers without ``segments.see_flagger_identity`` and
stamping a per-comment ``mine`` flag so a flagger can find their own comment
to edit (role-only labels can't disambiguate authorship).

Counting flagged segments (e.g. for the admin Review drawer) lives in
``count_flagged`` — derived straight from ``detailed.json`` entries.

Flask-free; the route supplies ``viewer_id`` + ``can_see_identity``.
"""

from __future__ import annotations


def _author(actor: dict, can_see_identity: bool) -> dict:
    """Role always; full login/id only when the viewer holds the capability."""
    out: dict = {"role": actor.get("role")}
    if can_see_identity:
        out["login"] = actor.get("login_at_time")
        out["id"] = actor.get("hf_user_id")
    return out


def _mine(actor: dict, viewer_id: str | None) -> bool:
    return bool(viewer_id) and actor.get("hf_user_id") == viewer_id


def _comment_view(node: dict, at_key: str, viewer_id: str | None, can_see_identity: bool) -> dict:
    actor = node.get("actor") or {}
    return {
        "comment": node.get("comment", ""),
        "at": node.get(at_key),
        "author": _author(actor, can_see_identity),
        "mine": _mine(actor, viewer_id),
    }


def flag_view(flag: dict, viewer_id: str | None, can_see_identity: bool) -> dict:
    """FE-facing flag dict: redacted authors, ``mine`` markers, reply thread."""
    view = _comment_view(flag, "flagged_at_utc", viewer_id, can_see_identity)
    view["follow_ups"] = [
        _comment_view(f, "at_utc", viewer_id, can_see_identity)
        for f in (flag.get("follow_ups") or [])
    ]
    return view


def count_flagged(entries: list[dict]) -> int:
    """Number of segments carrying a flag across ``detailed.json`` entries."""
    return sum(
        1 for entry in entries for seg in entry.get("segments", []) if seg.get("flag") is not None
    )
