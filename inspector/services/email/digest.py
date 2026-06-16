"""Email digest flush — collapse a window of buffered events into one email.

The two high-volume events buffer per recipient in ``email_digest`` (see
``services.db.repo_email_digest``); this module sweeps that buffer and, for each
(email, event_kind) group whose tumbling window has aged past
``EMAIL_DIGEST_WINDOW_MINUTES``, sends ONE batched email and deletes the flushed
rows. A single buffered reciter reuses the existing singular template; two or
more use the ``<event_kind>_digest`` template.

``flush_due`` is a pure, testable sweep; ``start_flush_daemon`` runs it on a
timer (mirrors the visitor-analytics / automation daemons — one daemon thread in
the single worker, every tick failure caught so one hiccup never kills the loop).
Send is fire-and-forget (the ``send`` pool) THEN delete, so a crash mid-flush
re-sends rather than drops (consistent with best-effort emails).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

import config

from . import send, templates
from .emit import _link_ctx

logger = logging.getLogger("email")

_DIGEST_EVENTS = ("recitation_published", "timestamps_regenerated")

_background_thread: threading.Thread | None = None


def _render(event_kind: str, reciter_names: list[str], manage_token: str) -> tuple[str, str]:
    """One buffered reciter → the singular template (natural copy); several →
    the batched digest template."""
    ctx = _link_ctx(manage_token)
    if len(reciter_names) == 1:
        ctx["reciter_name"] = reciter_names[0]
        return templates.render(event_kind, ctx)
    ctx["reciters"] = reciter_names
    ctx["count"] = len(reciter_names)
    return templates.render(f"{event_kind}_digest", ctx)


def _flush_group(email: str, event_kind: str) -> None:
    from services.db import repo_email_digest
    from services.db import sync as _sync

    items = repo_email_digest.items_for(email, event_kind)
    if not items:
        return
    # Dedup reciters for display (a reciter buffered twice in one window lists
    # once), preserving first-seen order; delete every read row by id.
    seen: set[str] = set()
    names: list[str] = []
    for it in items:
        if it["reciter_id"] in seen:
            continue
        seen.add(it["reciter_id"])
        names.append(it["reciter_name"])
    subject, html = _render(event_kind, names, items[0]["manage_token"])
    send.send(email, subject, html)
    with _sync.durable_transaction():
        repo_email_digest.delete_ids([it["id"] for it in items])


def flush_due(now: datetime | None = None) -> None:
    """Flush every (email, event_kind) group whose window has elapsed. Each group
    is best-effort: one group's failure never blocks the others."""
    from services.db import _serde, repo_email_digest

    now = now or _serde.now()
    cutoff = now - timedelta(minutes=config.EMAIL_DIGEST_WINDOW_MINUTES)
    for group in repo_email_digest.due_groups(cutoff=cutoff):
        try:
            _flush_group(group["email"], group["event_kind"])
        except Exception:  # noqa: BLE001 — never let one group kill the sweep
            logger.exception(
                "email digest flush failed (email=%s, event=%s)",
                group["email"],
                group["event_kind"],
            )


def start_flush_daemon(interval_seconds: int | None = None) -> threading.Thread:
    """Spawn the flush thread. Idempotent — returns the live thread if one runs."""
    global _background_thread
    if _background_thread is not None and _background_thread.is_alive():
        return _background_thread

    every = interval_seconds or config.EMAIL_DIGEST_FLUSH_INTERVAL_SECONDS

    def _loop() -> None:
        logger.info("email digest: flush loop started (interval=%ss)", every)
        while True:
            try:
                flush_due()
            except Exception:  # noqa: BLE001 — never let a tick kill the loop
                logger.exception("email digest: flush tick errored")
            time.sleep(every)

    t = threading.Thread(target=_loop, daemon=True, name="email-digest")
    t.start()
    _background_thread = t
    return t
