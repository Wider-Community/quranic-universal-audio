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

from scripts.lib.schemas import Actor, ArchivedRequest, PendingRequest, ProposedEdits

from . import _serde
from .connection import get_conn
from . import repo_access

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


def resolve(
    *,
    slug: str,
    status: str,                       # accepted | returned | discarded
    transitioned_by: Actor,
    reason: str | None = None,
    closed_by_transition_id: str | None = None,
    at: datetime | None = None,
) -> bool:
    """Move the open (pending) request for ``slug`` to a terminal status,
    stamping archival metadata into the payload. Returns True if one moved."""
    row = get_pending_row(slug)
    if row is None:
        return False
    repo_access.ensure_user(transitioned_by.hf_user_id, login=transitioned_by.login_at_time)
    payload = _serde.json_loads(row["payload"]) or {}
    payload["transitioned_by"] = _actor_dict(transitioned_by)
    get_conn().execute(
        "UPDATE requests SET status = ?, resolved_at = ?, resolved_by_id = ?, "
        "resolution_reason = ?, payload = ?, closed_by_transition_id = ? "
        "WHERE id = ?",
        (
            status,
            _serde.to_iso(at or _serde.now()),
            transitioned_by.hf_user_id,
            reason,
            _serde.json_dumps(payload),
            closed_by_transition_id,
            row["id"],
        ),
    )
    return True


# ---- reads ----


def get_pending_row(slug: str):
    return get_conn().execute(
        "SELECT * FROM requests WHERE slug = ? AND status = 'pending'", (slug,)
    ).fetchone()


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
    rows = get_conn().execute(
        "SELECT * FROM requests WHERE status = 'pending' AND slug IS NOT NULL "
        "ORDER BY submitted_at"
    ).fetchall()
    return [_to_pending(r) for r in rows]


def count_pending(*, include_slugless: bool = True) -> int:
    sql = "SELECT COUNT(*) FROM requests WHERE status = 'pending'"
    if not include_slugless:
        sql += " AND slug IS NOT NULL"
    return int(get_conn().execute(sql).fetchone()[0])


def get_for_slug(archive_kind: str, slug: str) -> list[ArchivedRequest]:
    """Archived requests for a slug, oldest→newest (parity with the old
    request_archive.get_for_slug(kind) list-per-slug order)."""
    status = _STATUS_FOR_ARCHIVE[archive_kind]
    rows = get_conn().execute(
        "SELECT * FROM requests WHERE slug = ? AND status = ? ORDER BY resolved_at, id",
        (slug, status),
    ).fetchall()
    return [_to_archived(r) for r in rows]
