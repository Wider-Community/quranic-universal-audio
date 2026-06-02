"""Identity recency + site visitor analytics (Flask-free).

Two concerns:

* **Signed-in recency (Tier 1).** ``maybe_touch_entry`` stamps
  ``users.last_entry_at`` from ``/api/me``, debounced so a browsing session is
  at most one write per user per ``ENTRY_DEBOUNCE_SECONDS`` (not per page load).

* **Traffic counters (Tier 2/3).** ``record_hit`` bumps in-memory anon vs
  signed-in counters (single-worker → one process, one lock). A daemon flushes
  them HOURLY into ``visitor_daily`` via one ``durable_transaction`` (one DB
  txn / one bucket upload per flush — never per request). ``unique_*`` are
  upper-bound estimates: a visitor active across multiple hours is counted once
  per flush (documented + accepted; the FE renders unique-anon with ``~``). No
  fingerprinting; the only anon identifier is an opaque random ``anon_id``
  cookie. IP is never stored.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from config import ENTRY_DEBOUNCE_SECONDS, VISITOR_FLUSH_INTERVAL_SECONDS

from scripts.lib.schemas import AdminVisitorStats, VisitorDayStat

from services.db import _serde, repo_access, repo_visitors
from services.db import sync as _sync

logger = logging.getLogger(__name__)

_VISITOR_STATS_RECENT_DAYS = 30


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ---------------------------------------------------------------------------
# Tier 1 — signed-in page-entry recency
# ---------------------------------------------------------------------------


def maybe_touch_entry(hf_user_id: str, *, now: datetime | None = None) -> bool:
    """Stamp ``last_entry_at`` only if the stored value is stale (older than
    ``ENTRY_DEBOUNCE_SECONDS``) or absent. Returns True if it wrote.

    Read-then-conditional-write: the read is a cheap reader query; only a stale
    entry opens a ``durable_transaction`` (→ one bucket upload). At steady state
    this is at most one write per active user per debounce window. A benign
    double-write under a thread race just costs one extra upload — never
    corrupts (single-active-writer invariant)."""
    now = now or _serde.now()
    last = repo_access.get_last_entry(hf_user_id)
    if last is not None:
        last_dt = _serde.from_iso(last)
        if last_dt is not None and (now - last_dt).total_seconds() < ENTRY_DEBOUNCE_SECONDS:
            return False
    with _sync.durable_transaction():
        repo_access.touch_last_entry(hf_user_id, now=now)
    return True


# ---------------------------------------------------------------------------
# Tier 2/3 — in-memory traffic counters
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_bucket: dict = {
    "signed_in_hits": 0,
    "anon_hits": 0,
    "signed_in_ids": set(),  # hf_user_id seen this period
    "anon_ids": set(),       # anon_id cookie values seen this period
}


def record_hit(payload: dict | None, *, anon_id: str | None = None) -> None:
    """Count one request. ``payload`` is the decoded session (signed-in) or
    None (anonymous). ``anon_id`` is the opaque cookie value for anon callers."""
    with _lock:
        if payload is not None:
            _bucket["signed_in_hits"] += 1
            hid = payload.get("hf_user_id")
            if hid:
                _bucket["signed_in_ids"].add(hid)
        else:
            _bucket["anon_hits"] += 1
            if anon_id:
                _bucket["anon_ids"].add(anon_id)


def live_counts() -> dict:
    """Current un-flushed bucket as a counts dict (no reset)."""
    with _lock:
        return {
            "signed_in_hits": _bucket["signed_in_hits"],
            "anon_hits": _bucket["anon_hits"],
            "unique_signed_in": len(_bucket["signed_in_ids"]),
            "unique_anon": len(_bucket["anon_ids"]),
        }


def _drain() -> dict:
    """Atomically read + reset the bucket → counts dict for the flush."""
    with _lock:
        snap = {
            "signed_in_hits": _bucket["signed_in_hits"],
            "anon_hits": _bucket["anon_hits"],
            "unique_signed_in": len(_bucket["signed_in_ids"]),
            "unique_anon": len(_bucket["anon_ids"]),
        }
        _bucket["signed_in_hits"] = 0
        _bucket["anon_hits"] = 0
        _bucket["signed_in_ids"] = set()
        _bucket["anon_ids"] = set()
    return snap


def flush(*, now: datetime | None = None) -> bool:
    """Drain the in-memory bucket into today's ``visitor_daily`` row. One DB
    txn → one bucket upload. No-op (no upload) when the bucket is empty.
    Returns True if it wrote."""
    snap = _drain()
    if not any(snap.values()):
        return False
    day = (now or datetime.now(timezone.utc)).date().isoformat()
    with _sync.durable_transaction():
        repo_visitors.upsert_day(day, **snap)
    return True


# ---- hourly flush daemon ----

_FLUSH_THREAD: threading.Thread | None = None
_FLUSH_STARTED = False
_STOPPING = False


def start_flush_daemon() -> None:
    """Idempotently start the hourly flush thread."""
    global _FLUSH_THREAD, _FLUSH_STARTED
    if _FLUSH_STARTED:
        return
    _FLUSH_THREAD = threading.Thread(
        target=_flush_loop, name="visitor-flush", daemon=True
    )
    _FLUSH_THREAD.start()
    _FLUSH_STARTED = True


def _flush_loop() -> None:
    while not _STOPPING:
        time.sleep(VISITOR_FLUSH_INTERVAL_SECONDS)
        try:
            flush()
        except Exception:  # noqa: BLE001
            logger.exception("visitor flush tick crashed")


# ---------------------------------------------------------------------------
# read model for /api/admin/visitor-stats
# ---------------------------------------------------------------------------


def get_visitor_stats() -> dict:
    """Today (persisted + live in-memory bucket so it isn't an hour stale) plus
    recent days. Not cached — must reflect the un-flushed bucket."""
    today = _today()
    persisted = repo_visitors.get_day(today) or {
        "signed_in_hits": 0, "anon_hits": 0, "unique_signed_in": 0, "unique_anon": 0,
    }
    live = live_counts()
    today_stat = VisitorDayStat(
        date=today,
        signed_in_hits=persisted["signed_in_hits"] + live["signed_in_hits"],
        anon_hits=persisted["anon_hits"] + live["anon_hits"],
        # over-counts a visitor seen both pre- and post-flush — accepted estimate.
        unique_signed_in=persisted["unique_signed_in"] + live["unique_signed_in"],
        unique_anon=persisted["unique_anon"] + live["unique_anon"],
    )
    recent = [VisitorDayStat(**d) for d in repo_visitors.recent_days(_VISITOR_STATS_RECENT_DAYS)]
    return AdminVisitorStats(today=today_stat, recent=recent).model_dump(mode="json")


def _reset_for_test() -> None:
    """Clear the in-memory bucket between tests."""
    with _lock:
        _bucket["signed_in_hits"] = 0
        _bucket["anon_hits"] = 0
        _bucket["signed_in_ids"] = set()
        _bucket["anon_ids"] = set()
