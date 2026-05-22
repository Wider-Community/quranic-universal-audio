"""Admin Requests-tab read models + per-admin view marks (Flask-free).

``list_requests()`` assembles the review-queue payload for one status facet:
a catalog-joined base list (cached on ``db_seq`` like ``admin/users.py``) with
a per-caller overlay applied live (requester redaction for maintainers, the
``viewed`` flag, and the caller's unviewed-open count).

``mark_viewed()`` records that the calling admin has seen a request — written
the first time they inline-expand it — mirroring the per-user dismissal pattern
in ``services/activity/activity_state.py``.

The proposed-changes ``changes`` list is built strictly over the
``ProposedEdits`` field set (the same fields the request form can edit), with
the current catalog value joined in as the ``from`` side.
"""

from __future__ import annotations

from services.auth import permissions
from services.db import _serde, repo_requests
from services.db import sync as _sync
from services.db.connection import current_db_seq
from services.state import catalog as catalog_service
from services.storage import cache

# UI status facet → DB status column value.
_STATUS_DB = {
    "open": "pending",
    "accepted": "accepted",
    "returned": "returned",
    "discarded": "discarded",
}

# (key, label) — MUST mirror ProposedEdits / the request form's editable fields.
_PROPOSED_FIELDS: list[tuple[str, str]] = [
    ("riwayah", "Riwayah"),
    ("style", "Style"),
    ("name_en", "English name"),
    ("name_ar", "Arabic name"),
    ("country", "Country"),
    ("recording_context", "Recording context"),
    ("recording_year", "Recording year"),
]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def list_requests(*, status: str, caller_is_owner: bool, caller_hf_id: str) -> dict:
    """Assembled Requests-tab payload (``AdminRequestsResponse`` shape).

    ``status`` is a UI facet (``open``/``accepted``/``returned``/``discarded``).
    Returns a plain dict ready to ``jsonify``.
    """
    db_status = _STATUS_DB.get(status, "pending")
    db_seq = current_db_seq()

    base = cache.get_admin_requests_cache(db_seq, db_status)
    if base is None:
        base = _build_base_rows(db_status)
        cache.set_admin_requests_cache(db_seq, db_status, base)

    viewed = (
        repo_requests.viewed_ids_for_user(caller_hf_id)
        if db_status == "pending"
        else set()
    )
    rows = [_serialize(r, owner=caller_is_owner, viewed=viewed) for r in base]

    counts = repo_requests.counts_by_status()
    return {
        "rows": rows,
        "counts": {
            "open": counts.get("pending", 0),
            "accepted": counts.get("accepted", 0),
            "returned": counts.get("returned", 0),
            "discarded": counts.get("discarded", 0),
        },
        "unviewed_count": repo_requests.count_unviewed_open_for_user(caller_hf_id),
    }


def unviewed_count(*, caller_hf_id: str) -> int:
    """Open requests the calling admin has not yet viewed (badge source)."""
    return repo_requests.count_unviewed_open_for_user(caller_hf_id)


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def mark_viewed(request_id: str, *, actor) -> bool:
    """Mark ``request_id`` viewed for ``actor`` (idempotent). Returns False if
    the request id is unknown. The first view per (request, admin) is a durable
    write; repeats short-circuit so an expand doesn't churn the bucket."""
    if repo_requests.is_viewed(request_id, actor.hf_user_id):
        return True
    if repo_requests.get_by_id(request_id) is None:
        return False
    with _sync.durable_transaction():
        repo_requests.mark_viewed(request_id, actor.hf_user_id)
    return True


# ---------------------------------------------------------------------------
# Base-row assembly (caller-agnostic; cached)
# ---------------------------------------------------------------------------


def _build_base_rows(db_status: str) -> list[dict]:
    out: list[dict] = []
    for row in repo_requests.admin_list_rows(status=db_status):
        payload = _serde.json_loads(row["payload"]) or {}
        slug = row["slug"]

        delivery = catalog_service.find_delivery(slug) if slug else None
        reciter = (
            catalog_service.find_reciter(delivery.reciter_id)
            if delivery is not None
            else None
        )
        name_en = reciter.name_en if reciter is not None else None
        if name_en is None:
            name_en = catalog_service.display_name(slug) or slug
        name_ar = reciter.name_ar if reciter is not None else None
        riwayah = delivery.riwayah if delivery is not None else None
        style = delivery.style if delivery is not None else None

        proposed = payload.get("proposed_edits") or {}
        current = _current_values(delivery, reciter)

        out.append({
            "id": row["id"],
            "slug": slug,
            "kind": row["kind"],
            "status": row["status"],
            "submitted_at": row["submitted_at"],
            "resolved_at": row["resolved_at"],
            "resolution_reason": row["resolution_reason"],
            "auto_claim": bool(row["auto_claim"]),
            "comments": row["comments"],
            "name_en": name_en,
            "name_ar": name_ar,
            "riwayah": riwayah,
            "style": style,
            "proposed_edits": proposed,
            "changes": _changes_list(proposed, current),
            "conflict": _conflict(slug, delivery, proposed),
            "_requester": payload.get("requester") or {},
            "_transitioned_by": payload.get("transitioned_by") or {},
        })
    return out


def _current_values(delivery, reciter) -> dict:
    cur: dict[str, object] = {}
    if delivery is not None:
        cur["riwayah"] = delivery.riwayah
        cur["style"] = delivery.style
        cur["recording_context"] = getattr(delivery, "recording_context", None)
        cur["recording_year"] = getattr(delivery, "recording_year", None)
    if reciter is not None:
        cur["name_en"] = reciter.name_en
        cur["name_ar"] = reciter.name_ar
        cur["country"] = getattr(reciter, "country", None)
    return cur


def _changes_list(proposed: dict, current: dict) -> list[dict]:
    """One entry per populated ProposedEdits field, with the joined ``from``."""
    out: list[dict] = []
    for key, label in _PROPOSED_FIELDS:
        new = proposed.get(key)
        if new is None:
            continue
        out.append({"field": key, "label": label, "from": current.get(key), "to": new})
    return out


def _conflict(slug, delivery, proposed: dict) -> bool:
    """True iff the proposed (riwayah, style) — when changed — collides with
    another delivery of the same reciter. Mirrors the request form's predicate
    and ``pending_requests._apply_edits``; non-blocking, advisory only."""
    if delivery is None:
        return False
    proposed_riwayah = proposed.get("riwayah") or delivery.riwayah
    proposed_style = proposed.get("style") or delivery.style
    if proposed_riwayah == delivery.riwayah and proposed_style == delivery.style:
        return False
    catalog = catalog_service.snapshot()
    return any(
        d.slug != slug
        and d.reciter_id == delivery.reciter_id
        and d.riwayah == proposed_riwayah
        and d.style == proposed_style
        for d in catalog.deliveries
    )


def _serialize(base_row: dict, *, owner: bool, viewed: set[str]) -> dict:
    out = {k: v for k, v in base_row.items() if not k.startswith("_")}
    requester = base_row["_requester"]
    out["requester_role"] = requester.get("role")
    if owner:
        out["requester_login"] = requester.get("login_at_time")
        out["requester_hf_user_id"] = requester.get("hf_user_id")
    out["viewed"] = base_row["id"] in viewed

    tb = base_row["_transitioned_by"]
    if tb:
        out["resolved_by_role"] = tb.get("role")
        if owner:
            out["resolved_by_login"] = tb.get("login_at_time")
    return out
