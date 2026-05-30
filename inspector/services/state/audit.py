"""Audit log: thin facade over the SQLite ``transitions`` table.

The canonical event log is ``transitions`` (``repo_transitions``). This module
keeps the legacy ``audit.append(event, …)`` signature so the ~16 call sites
(state, catalog, access, activity) don't churn. It delegates
to ``repo_transitions.append`` which enrolls in the caller's active
``transaction()`` (a SAVEPOINT when nested) — so the transition row commits
atomically with the state/claim/catalog write that motivated it, and its
durability rides the boundary's ``durable_transaction`` upload.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from scripts.lib.schemas import Actor, AuditRecord

from services.db import repo_transitions

logger = logging.getLogger(__name__)


def append(
    event: str,
    *,
    actor: Actor,
    slug: str | None = None,
    from_state: str | None = None,
    to_state: str | None = None,
    payload: dict[str, Any] | None = None,
    request_id: str | None = None,
    reason: str | None = None,
    result: Literal["ok", "error"] = "ok",
) -> AuditRecord:
    """Append one transition row and return the equivalent ``AuditRecord``.

    Must run inside an active ``transaction()`` for state/catalog/access events
    (so it's atomic with the motivating write); ``repo_transitions.append``
    self-commits only for genuinely standalone audits.
    """
    rec = repo_transitions.append(
        event=event,
        actor=actor,
        slug=slug,
        from_state=from_state,
        to_state=to_state,
        payload=payload,
        request_id=request_id,
        reason=reason,
        result=result,
    )
    logger.info("audit %s slug=%s event=%s", rec.request_id, slug or "-", event)
    return rec
