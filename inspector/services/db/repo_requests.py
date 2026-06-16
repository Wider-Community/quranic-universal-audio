"""Repository for the unified ``requests`` table (pending + archives).

Collapses ``requests/pending.json`` + the 3 archive files. The evolving
add-reciter wizard fields live in the JSON ``payload`` column (forward-
compatible: new ``kind``s / fields need no migration). Adapters rebuild the
legacy ``PendingRequest`` / ``ArchivedRequest`` shapes so the accept flow
(``apply_and_archive_completed`` → ``proposed_edits.has_any()``) and the
admin/FE wire contract keep working.

Status mapping vs the old archive files:
    accepted  ← requests/completed.json
    returned  ← requests/returned.json
    discarded ← requests/discarded.json
"""

from __future__ import annotations

import uuid
from datetime import datetime

from qua_shared.schemas import Actor, ArchivedRequest, PendingRequest, ProposedEdits

from . import _serde, repo_access
from .connection import get_conn

_STATUS_FOR_ARCHIVE = {"completed": "accepted", "returned": "returned", "discarded": "discarded"}


def _new_request_id() -> str:
    return f"rq_{uuid.uuid4().hex[:12]}"


def _actor_dict(actor: Actor) -> dict:
    return {
        "hf_user_id": actor.hf_user_id,
        "login_at_time": actor.login_at_time,
        "role": actor.role.value if hasattr(actor.role, "value") else str(actor.role),
    }


# ---- adapters ----


def _to_pending(row) -> PendingRequest:
    payload = _serde.json_loads(row["payload"]) or {}
    return PendingRequest(
        slug=row["slug"],
        submitted_at=_serde.from_iso(row["submitted_at"]),
        requester=Actor(**payload["requester"]),
        proposed_edits=ProposedEdits(**(payload.get("proposed_edits") or {})),
        comments=row["comments"],
        auto_claim=bool(row["auto_claim"]),
    )


def _to_archived(row) -> ArchivedRequest:
    payload = _serde.json_loads(row["payload"]) or {}
    return ArchivedRequest(
        slug=row["slug"],
        submitted_at=_serde.from_iso(row["submitted_at"]),
        requester=Actor(**payload["requester"]),
        proposed_edits=ProposedEdits(**(payload.get("proposed_edits") or {})),
        comments=row["comments"],
        auto_claim=bool(row["auto_claim"]),
        archived_at=_serde.from_iso(row["resolved_at"]),
        transitioned_by=Actor(**payload["transitioned_by"]),
        reason=row["resolution_reason"],
    )


# ---- writes (caller owns the transaction) ----


def submit(
    *,
    slug: str | None,
    requester: Actor,
    proposed_edits: ProposedEdits | None = None,
    comments: str | None = None,
    auto_claim: bool = False,
    kind: str = "existing_combo_edit",
    opened_by_transition_id: str | None = None,
    extra_payload: dict | None = None,
) -> str:
    """Insert a pending request. Returns the request id. The pending-per-slug
    unique index rejects a second open request for the same (non-null) slug."""
    repo_access.ensure_user(requester.hf_user_id, login=requester.login_at_time)
    payload: dict = {
        "requester": _actor_dict(requester),
        "proposed_edits": (proposed_edits or ProposedEdits()).model_dump(mode="json"),
    }
    if extra_payload:
        clash = {"requester", "proposed_edits"} & set(extra_payload)
        if clash:
            raise ValueError(f"extra_payload may not override reserved keys: {sorted(clash)}")
        payload.update(extra_payload)
    rid = _new_request_id()
    get_conn().execute(
        "INSERT INTO requests(id, kind, slug, requester_id, submitted_at, status, "
        "auto_claim, comments, payload, opened_by_transition_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            rid,
            kind,
            slug,
            requester.hf_user_id,
            _serde.to_iso(_serde.now()),
            "pending",
            1 if auto_claim else 0,
            comments,
            _serde.json_dumps(payload),
            opened_by_transition_id,
        ),
    )
    return rid


def _resolve_row(
    row,
    *,
    status: str,
    transitioned_by: Actor,
    reason: str | None,
    slug: str | None,
    closed_by_transition_id: str | None,
    at: datetime | None,
) -> bool:
    """Shared resolution core. Stamps the terminal status + archival metadata on
    one already-fetched pending row. ``slug`` back-fills ``requests.slug`` when
    given (intake accept mints a delivery and links it); ``None`` keeps the
    existing slug. Both the slug-keyed and id-keyed entry points funnel here so
    the status-mutation logic lives in exactly one place."""
    repo_access.ensure_user(transitioned_by.hf_user_id, login=transitioned_by.login_at_time)
    payload = _serde.json_loads(row["payload"]) or {}
    payload["transitioned_by"] = _actor_dict(transitioned_by)
    new_slug = slug if slug is not None else row["slug"]
    get_conn().execute(
        "UPDATE requests SET status = ?, resolved_at = ?, resolved_by_id = ?, "
        "resolution_reason = ?, payload = ?, closed_by_transition_id = ?, slug = ? "
        "WHERE id = ?",
        (
            status,
            _serde.to_iso(at or _serde.now()),
            transitioned_by.hf_user_id,
            reason,
            _serde.json_dumps(payload),
            closed_by_transition_id,
            new_slug,
            row["id"],
        ),
    )
    return True


def resolve(
    *,
    slug: str,
    status: str,  # accepted | returned | discarded
    transitioned_by: Actor,
    reason: str | None = None,
    closed_by_transition_id: str | None = None,
    at: datetime | None = None,
) -> bool:
    """Move the open (pending) request for ``slug`` to a terminal status,
    stamping archival metadata into the payload. Returns True if one moved.
    Slug-keyed path used by the edit-request (state-machine) flow."""
    row = get_pending_row(slug)
    if row is None:
        return False
    return _resolve_row(
        row,
        status=status,
        transitioned_by=transitioned_by,
        reason=reason,
        slug=None,
        closed_by_transition_id=closed_by_transition_id,
        at=at,
    )


def resolve_by_id(
    *,
    request_id: str,
    status: str,  # accepted | returned | discarded
    transitioned_by: Actor,
    reason: str | None = None,
    slug: str | None = None,
    closed_by_transition_id: str | None = None,
    at: datetime | None = None,
) -> bool:
    """Resolve a pending request by id (slugless intake flow — no state machine).
    ``slug`` optionally links a freshly-minted delivery on accept. Returns False
    if the id is unknown or already terminal.

    Back-fill exception: an already-``accepted`` intake row whose slug is still
    NULL may be re-resolved to ``accepted`` *to attach* the minted ``slug`` (the
    ingest step — accept flips the row to ``accepted`` before ingest mints the
    delivery). The status doesn't change; only the slug is attached. Re-resolving
    a non-accepted terminal row, or one whose slug is already set, returns
    False."""
    row = get_by_id(request_id)
    if row is None:
        return False
    if row["status"] != "pending":
        is_slug_backfill = (
            status == "accepted"
            and row["status"] == "accepted"
            and row["slug"] is None
            and slug is not None
        )
        if not is_slug_backfill:
            return False
    return _resolve_row(
        row,
        status=status,
        transitioned_by=transitioned_by,
        reason=reason,
        slug=slug,
        closed_by_transition_id=closed_by_transition_id,
        at=at,
    )


def set_payload(request_id: str, payload: dict) -> bool:
    """Overwrite a request's ``payload`` JSON (caller merges first — e.g. probe
    cache write reads, sets ``payload['probe']``, then writes back). Returns
    True if a row matched."""
    cur = get_conn().execute(
        "UPDATE requests SET payload = ? WHERE id = ?",
        (_serde.json_dumps(payload), request_id),
    )
    return cur.rowcount > 0


def delete_pending(slug: str) -> bool:
    """Hard-delete the open pending request for ``slug`` (no archive). Returns
    True if one was removed. Backs the legacy ``pending_requests.clear``."""
    cur = get_conn().execute("DELETE FROM requests WHERE slug = ? AND status = 'pending'", (slug,))
    return cur.rowcount > 0


# ---- reads ----


def get_pending_row(slug: str):
    return (
        get_conn()
        .execute("SELECT * FROM requests WHERE slug = ? AND status = 'pending'", (slug,))
        .fetchone()
    )


def get_pending(slug: str) -> PendingRequest | None:
    row = get_pending_row(slug)
    return _to_pending(row) if row else None


def has_pending(slug: str) -> bool:
    return get_pending_row(slug) is not None


def all_pending() -> list[PendingRequest]:
    """Slug-bearing pending requests as the legacy ``PendingRequest`` shape
    (parity with the old slug-keyed ``pending.json``). Slugless ``new_reciter``
    requests are a newer kind not representable here — surface them via the
    wizard-specific path when that feature lands."""
    rows = (
        get_conn()
        .execute(
            "SELECT * FROM requests WHERE status = 'pending' AND slug IS NOT NULL "
            "ORDER BY submitted_at"
        )
        .fetchall()
    )
    return [_to_pending(r) for r in rows]


def count_pending(*, include_slugless: bool = True) -> int:
    sql = "SELECT COUNT(*) FROM requests WHERE status = 'pending'"
    if not include_slugless:
        sql += " AND slug IS NOT NULL"
    return int(get_conn().execute(sql).fetchone()[0])


def all_archived(archive_kind: str) -> list[ArchivedRequest]:
    """All archived requests for a terminal status (oldest→newest). Backs the
    legacy ``request_archive.snapshot(kind)`` reassembly."""
    status = _STATUS_FOR_ARCHIVE[archive_kind]
    rows = (
        get_conn()
        .execute(
            "SELECT * FROM requests WHERE status = ? AND slug IS NOT NULL "
            "ORDER BY resolved_at, submitted_at, id",
            (status,),
        )
        .fetchall()
    )
    return [_to_archived(r) for r in rows]


def get_for_slug(archive_kind: str, slug: str) -> list[ArchivedRequest]:
    """Archived requests for a slug, oldest→newest (parity with the old
    request_archive.get_for_slug(kind) list-per-slug order)."""
    status = _STATUS_FOR_ARCHIVE[archive_kind]
    rows = (
        get_conn()
        .execute(
            "SELECT * FROM requests WHERE slug = ? AND status = ? "
            "ORDER BY resolved_at, submitted_at, id",
            (slug, status),
        )
        .fetchall()
    )
    return [_to_archived(r) for r in rows]


def get_by_id(request_id: str):
    return get_conn().execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()


def ids_for_slug(slug: str) -> list[str]:
    """Every request id ever linked to ``slug`` (any status). Drives the
    auto-archive of the per-owner ``request.received`` alerts once the reciter
    reaches review — an intake row's slug is back-filled at ingest, a slug-based
    edit request carries it from creation, so both are reachable here."""
    rows = get_conn().execute("SELECT id FROM requests WHERE slug = ?", (slug,)).fetchall()
    return [r[0] for r in rows]


def admin_list_rows(*, status: str) -> list:
    """Raw rows for the admin Requests tab. ``status`` is a DB status
    (``pending``/``accepted``/``returned``/``discarded``). Includes slugless
    intake rows (new-combo / new-reciter) alongside slug-based edit requests.
    Pending is ordered oldest-first (longest-waiting on top); terminal statuses
    newest-resolved first. Returns sqlite Rows; the service maps + redacts."""
    if status == "pending":
        order = "submitted_at ASC"
    else:
        order = "resolved_at DESC, submitted_at DESC, id DESC"
    return (
        get_conn()
        .execute(
            f"SELECT * FROM requests WHERE status = ? ORDER BY {order}",
            (status,),
        )
        .fetchall()
    )


def counts_by_status() -> dict[str, int]:
    """``{status: count}`` over all requests — edit + intake (drives the facet
    chips)."""
    rows = get_conn().execute("SELECT status, COUNT(*) FROM requests GROUP BY status").fetchall()
    return {r[0]: int(r[1]) for r in rows}
