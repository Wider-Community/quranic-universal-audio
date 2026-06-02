"""Per-user "read" marks for the validation-accordion help guides.

One row per (guide ``view_key``, user) the first time that user opens the
guide. The set powers the FE unread border + the first-edit onboarding gate
(see ``docs/reference/accordion-guides.md``). Mirrors ``repo_review_views`` but
write-once: ``INSERT OR IGNORE`` — once a guide is read it stays read, so there
is no unread transition and no ``viewed_at`` advance.

``view_key`` is the *collapsed* form (``low_confidence_v2`` folds into
``low_confidence`` — one required reading); the route normalises before calling
in so the table never holds the alias. The caller owns the transaction (the
route wraps the write in ``sync.durable_transaction``).
"""

from __future__ import annotations

from datetime import datetime

from . import _serde
from .connection import get_conn
from . import repo_access


def record_view(hf_user_id: str, view_key: str, *, at: datetime | None = None) -> None:
    """Mark ``view_key`` read for this user (idempotent first-write-wins).

    ``ensure_user`` keeps the FK valid for callers whose ``users`` row hasn't
    been created yet (mirrors ``repo_review_views.mark_viewed``).
    """
    repo_access.ensure_user(hf_user_id)
    get_conn().execute(
        "INSERT OR IGNORE INTO guide_views(view_key, hf_user_id, viewed_at) "
        "VALUES (?,?,?)",
        (view_key, hf_user_id, _serde.to_iso(at or _serde.now())),
    )


def read_views(hf_user_id: str) -> list[str]:
    """Every guide ``view_key`` this user has opened (order-stable by key).

    ``/api/me`` calls this once per request; the FE diffs it against the
    required-guide set to render unread borders + lift the edit gate.
    """
    rows = get_conn().execute(
        "SELECT view_key FROM guide_views WHERE hf_user_id = ? ORDER BY view_key",
        (hf_user_id,),
    ).fetchall()
    return [r[0] for r in rows]
