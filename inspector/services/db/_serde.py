"""Serialization helpers shared by the DB repositories.

- datetimes ↔ ISO-8601 UTC strings (the on-disk column format)
- JSON columns via orjson
- content_hash: the stable, content-derived id the activity layer uses for
  dismissals/tombstones. MUST stay byte-identical to
  ``services.activity.activity_classification.audit_id`` so migrated
  dismissals/tombstones keep matching their transitions.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

import orjson


def now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def from_iso(s: str | None) -> datetime | None:
    if s is None:
        return None
    return datetime.fromisoformat(s)


def json_dumps(obj: Any) -> str:
    return orjson.dumps(obj).decode("utf-8")


def json_loads(s: str | None) -> Any:
    if s is None or s == "":
        return None
    return orjson.loads(s)


def new_transition_id() -> str:
    """Stable external id for a transition row (mirrors the old audit
    ``request_id`` format so external references survive migration)."""
    return f"req_{uuid.uuid4().hex[:12]}"


def content_hash(
    *,
    ts: str,
    event: str,
    slug: str | None,
    actor_hf: str | None,
    result: str = "ok",
) -> str:
    """sha1(ts|event|slug|actor_hf|result)[:16] — see activity_classification.audit_id.

    Components are the *string* forms exactly as stored, so a record written
    here and a record read back hash identically.
    """
    raw = f"{ts or ''}|{event or ''}|{slug or ''}|{actor_hf or ''}|{result or 'ok'}".encode(
        "utf-8"
    )
    return hashlib.sha1(raw, usedforsecurity=False).hexdigest()[:16]


def content_hash_for_record(record: dict) -> str:
    """Compute the content hash from a raw audit/transition record dict.

    Used by the JSON→SQLite migration on historical audit JSONL records so the
    result matches what ``activity_classification.audit_id`` produced for the
    same record (the key the dismissal/tombstone stores point at)."""
    actor = record.get("actor") or {}
    actor_hf = actor.get("hf_user_id") if isinstance(actor, dict) else None
    return content_hash(
        ts=record.get("ts") or "",
        event=record.get("event") or "",
        slug=record.get("slug"),
        actor_hf=actor_hf,
        result=record.get("result") or "ok",
    )
