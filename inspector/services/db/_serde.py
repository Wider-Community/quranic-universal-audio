"""Serialization helpers shared by the DB repositories.

- datetimes ↔ ISO-8601 UTC strings (the on-disk column format)
- JSON columns via orjson
- content_hash: the stable, content-derived id the activity layer uses for
  global tombstones. MUST stay byte-identical to
  ``services.activity.activity_classification.audit_id`` so migrated
  tombstones keep matching their transitions.
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
    """ISO-8601 UTC string in the EXACT form pydantic ``model_dump(mode="json")``
    emits — a ``Z`` suffix, not ``+00:00`` (pydantic v2). Stored timestamps and
    pydantic-serialized wire timestamps must be byte-identical so activity cards
    (which emit the raw stored ``ts`` string) match what the rest of the app
    produced before the cutover. See ``activity`` feed parity tests."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    s = dt.isoformat()
    # isoformat() renders UTC as "+00:00"; pydantic renders it as "Z".
    if s.endswith("+00:00"):
        s = s[:-6] + "Z"
    return s


def from_iso(s: str | None) -> datetime | None:
    if s is None:
        return None
    # Python < 3.11 fromisoformat() doesn't handle the trailing "Z" suffix.
    if isinstance(s, str) and s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    # Stored values are always UTC; force tz-awareness for inputs that lack a
    # suffix (e.g. legacy strings) so round-trips stay deterministic.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


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
    same record (the key the tombstone store points at)."""
    actor = record.get("actor") or {}
    actor_hf = actor.get("hf_user_id") if isinstance(actor, dict) else None
    return content_hash(
        ts=record.get("ts") or "",
        event=record.get("event") or "",
        slug=record.get("slug"),
        actor_hf=actor_hf,
        result=record.get("result") or "ok",
    )
