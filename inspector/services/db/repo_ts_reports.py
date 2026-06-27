"""Categorized, cell-addressable Timestamps-tab reports (table ``ts_reports``).

Typed reports that point at a flexible target and carry an owner resolution
loop. One row per ``(slug, verse_key, category, target_key, identity)`` —
identity being EITHER a signed-in ``hf_user_id`` OR an anonymous browser
``anon_token`` (exactly one is set). A user may file multiple reports on a verse
(one per category+target), so ``target_key`` is the canonical descriptor string
the per-identity uniqueness keys on; re-submitting the same category+target as
the same identity updates the report in place.

``snap_*`` is the denormalized snapshot of the targeted shard content at create
time — the drift fingerprint a regeneration re-matches against to flip ``stale``
(see ``services/ts_reports/ts_target_snapshot.py``).

The caller owns the transaction: writes assume an active ``durable_transaction``;
reads use ``get_conn()`` directly. ``repo_access.ensure_user`` keeps the nullable
FK valid for signed-in reports.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import _serde, repo_access
from .connection import get_conn


def chapter_of(verse_key: str) -> int:
    """Surah number from a ``"surah:ayah"`` verse key."""
    return int(verse_key.split(":", 1)[0])


def target_key(target: dict[str, Any]) -> str:
    """Canonical key for a target descriptor (NULLs as empty), for ON CONFLICT.

    ``kind:word_index:source_letter_index:cell_index:phoneme_flat_index:share_group``.
    """

    def _s(v: Any) -> str:
        return "" if v is None else str(v)

    return ":".join(
        (
            str(target.get("kind", "")),
            _s(target.get("word_index")),
            _s(target.get("source_letter_index")),
            _s(target.get("cell_index")),
            _s(target.get("phoneme_flat_index")),
            _s(target.get("share_group")),
        )
    )


def _row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "slug": row["slug"],
        "verse_key": row["verse_key"],
        "chapter": row["chapter"],
        "category": row["category"],
        "subtype": row["subtype"],
        "target": {
            "kind": row["target_kind"],
            "word_index": row["word_index"],
            "source_letter_index": row["source_letter_index"],
            "cell_index": row["cell_index"],
            "phoneme_flat_index": row["phoneme_flat_index"],
            "share_group": row["share_group"],
        },
        "snapshot": {
            "chars": row["snap_chars"],
            "role": row["snap_role"],
            "status": row["snap_status"],
            "tag": row["snap_tag"],
            "secondary_tags": _serde.json_loads(row["snap_secondary_tags"]) or [],
            "phoneme_rule_tags": _serde.json_loads(row["snap_phoneme_rule_tags"]) or [],
            "phones": _serde.json_loads(row["snap_phones"]) or [],
            "share_group": row["snap_share_group"],
            "word_text": row["snap_word_text"],
            "verse_text": row["snap_verse_text"],
            "schema_version": row["snap_schema_version"],
        },
        "comment": row["comment"],
        "hf_user_id": row["hf_user_id"],
        "anon_token": row["anon_token"],
        "login_at_time": row["login_at_time"],
        "role_at_time": row["role_at_time"],
        "status": row["status"],
        "resolved_by_hf_user_id": row["resolved_by_hf_user_id"],
        "resolved_by_login": row["resolved_by_login"],
        "resolver_comment": row["resolver_comment"],
        "resolved_at": _serde.from_iso(row["resolved_at"]),
        "stale": bool(row["stale"]),
        "stale_at": _serde.from_iso(row["stale_at"]),
        "created_at": _serde.from_iso(row["created_at"]),
        "updated_at": _serde.from_iso(row["updated_at"]),
    }


# --- reads -----------------------------------------------------------------


def verse_counts(slug: str) -> list[dict[str, Any]]:
    """Per-verse open/resolved counts for a reciter, ordered by verse. Feeds the
    reported-verses accordion (verse pills + count badges)."""
    rows = (
        get_conn()
        .execute(
            "SELECT verse_key, "
            "SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_count, "
            "SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) AS resolved_count "
            "FROM ts_reports WHERE slug = ? GROUP BY verse_key ORDER BY verse_key",
            (slug,),
        )
        .fetchall()
    )
    return [
        {
            "verse_key": r["verse_key"],
            "open_count": r["open_count"],
            "resolved_count": r["resolved_count"],
        }
        for r in rows
    ]


def list_for_verse(slug: str, verse_key: str) -> list[dict[str, Any]]:
    """Every report on a verse (all identities + statuses), oldest first."""
    rows = (
        get_conn()
        .execute(
            "SELECT * FROM ts_reports WHERE slug = ? AND verse_key = ? ORDER BY created_at, id",
            (slug, verse_key),
        )
        .fetchall()
    )
    return [_row_to_dict(r) for r in rows]


def my_reports(
    slug: str, *, hf_user_id: str | None, anon_token: str | None
) -> list[dict[str, Any]]:
    """The caller's own reports for a reciter, newest first."""
    if (hf_user_id is None) == (anon_token is None):
        raise ValueError("exactly one of hf_user_id / anon_token must be set")
    col = "hf_user_id" if hf_user_id is not None else "anon_token"
    val = hf_user_id if hf_user_id is not None else anon_token
    rows = (
        get_conn()
        .execute(
            f"SELECT * FROM ts_reports WHERE slug = ? AND {col} = ? ORDER BY created_at DESC, id DESC",
            (slug, val),
        )
        .fetchall()
    )
    return [_row_to_dict(r) for r in rows]


def get(report_id: int) -> dict[str, Any] | None:
    row = get_conn().execute("SELECT * FROM ts_reports WHERE id = ?", (report_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_open_for_recheck(slug: str, *, chapters: list[int] | None) -> list[dict[str, Any]]:
    """Open, not-yet-stale reports for a slug, optionally scoped to ``chapters``.

    Drives the post-regeneration staleness recheck. ``chapters=None`` returns
    every open report for the slug (full/unknown-scope regen)."""
    if chapters is not None and not chapters:
        return []
    sql = "SELECT * FROM ts_reports WHERE slug = ? AND status = 'open' AND stale = 0"
    params: list[Any] = [slug]
    if chapters is not None:
        sql += f" AND chapter IN ({','.join('?' for _ in chapters)})"
        params.extend(chapters)
    rows = get_conn().execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


# --- writes (caller owns the durable_transaction) --------------------------


def create(
    *,
    slug: str,
    verse_key: str,
    category: str,
    subtype: str | None,
    target: dict[str, Any],
    snapshot: dict[str, Any] | None,
    comment: str | None,
    hf_user_id: str | None,
    anon_token: str | None,
    login_at_time: str | None,
    role_at_time: str | None,
    at: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    """Insert the caller's report (or update it on a repeat of the same
    category+target). Returns ``(row, created)`` where ``created`` is True when a
    new report was inserted (drives notify-on-new). Exactly one of ``hf_user_id``
    / ``anon_token`` must be set."""
    if (hf_user_id is None) == (anon_token is None):
        raise ValueError("exactly one of hf_user_id / anon_token must be set")
    if hf_user_id is not None:
        repo_access.ensure_user(hf_user_id)
    tkey = target_key(target)
    snap = snapshot or {}
    created = _current(slug, verse_key, category, tkey, hf_user_id, anon_token) is None
    ts = _serde.to_iso(at or _serde.now())
    conflict_col = "hf_user_id" if hf_user_id is not None else "anon_token"
    get_conn().execute(
        "INSERT INTO ts_reports("
        " slug, verse_key, chapter, category, subtype,"
        " target_kind, word_index, source_letter_index, cell_index, phoneme_flat_index,"
        " share_group, target_key,"
        " snap_chars, snap_role, snap_status, snap_tag, snap_secondary_tags,"
        " snap_phoneme_rule_tags, snap_phones, snap_share_group, snap_word_text,"
        " snap_verse_text, snap_schema_version,"
        " hf_user_id, anon_token, login_at_time, role_at_time, comment,"
        " status, stale, created_at, updated_at)"
        " VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?, ?,?,?,?,?, ?,?,?,?, ?,?, ?,?,?,?,?, 'open',0,?,?)"
        f" ON CONFLICT(slug, verse_key, category, target_key, {conflict_col})"
        f" WHERE {conflict_col} IS NOT NULL DO UPDATE SET"
        "   subtype = excluded.subtype,"
        "   snap_chars = excluded.snap_chars, snap_role = excluded.snap_role,"
        "   snap_status = excluded.snap_status, snap_tag = excluded.snap_tag,"
        "   snap_secondary_tags = excluded.snap_secondary_tags,"
        "   snap_phoneme_rule_tags = excluded.snap_phoneme_rule_tags,"
        "   snap_phones = excluded.snap_phones, snap_share_group = excluded.snap_share_group,"
        "   snap_word_text = excluded.snap_word_text, snap_verse_text = excluded.snap_verse_text,"
        "   snap_schema_version = excluded.snap_schema_version,"
        "   comment = excluded.comment, updated_at = excluded.updated_at",
        (
            slug,
            verse_key,
            chapter_of(verse_key),
            category,
            subtype,
            target.get("kind"),
            target.get("word_index"),
            target.get("source_letter_index"),
            target.get("cell_index"),
            target.get("phoneme_flat_index"),
            target.get("share_group"),
            tkey,
            snap.get("chars"),
            snap.get("role"),
            snap.get("status"),
            snap.get("tag"),
            _serde.json_dumps(snap["secondary_tags"]) if snap.get("secondary_tags") else None,
            _serde.json_dumps(snap["phoneme_rule_tags"]) if snap.get("phoneme_rule_tags") else None,
            _serde.json_dumps(snap["phones"]) if snap.get("phones") else None,
            snap.get("share_group"),
            snap.get("word_text"),
            snap.get("verse_text"),
            snap.get("schema_version"),
            hf_user_id,
            anon_token,
            login_at_time,
            role_at_time,
            comment,
            ts,
            ts,
        ),
    )
    row = _current(slug, verse_key, category, tkey, hf_user_id, anon_token)
    assert row is not None  # just inserted/updated
    return row, created


def resolve(
    *,
    report_id: int,
    resolver_hf_user_id: str | None,
    resolver_login: str | None,
    resolver_comment: str | None,
    at: datetime | None = None,
) -> dict[str, Any] | None:
    """Mark an open report resolved. Returns the updated row (incl. reporter
    identity, for the resolution notification), or ``None`` if the report does
    not exist or is already resolved."""
    if resolver_hf_user_id is not None:
        repo_access.ensure_user(resolver_hf_user_id)
    ts = _serde.to_iso(at or _serde.now())
    cur = get_conn().execute(
        "UPDATE ts_reports SET status = 'resolved', resolved_by_hf_user_id = ?,"
        " resolved_by_login = ?, resolver_comment = ?, resolved_at = ?, updated_at = ?"
        " WHERE id = ? AND status = 'open'",
        (resolver_hf_user_id, resolver_login, resolver_comment, ts, ts, report_id),
    )
    if cur.rowcount == 0:
        return None
    return get(report_id)


def mark_stale(report_ids: list[int], *, at: datetime | None = None) -> int:
    """Flag the given reports stale (idempotent). Returns rows changed."""
    if not report_ids:
        return 0
    ts = _serde.to_iso(at or _serde.now())
    cur = get_conn().execute(
        f"UPDATE ts_reports SET stale = 1, stale_at = ?, updated_at = ? "
        f"WHERE stale = 0 AND id IN ({','.join('?' for _ in report_ids)})",
        (ts, ts, *report_ids),
    )
    return cur.rowcount


def delete(*, report_id: int, hf_user_id: str | None, anon_token: str | None) -> bool:
    """Delete the caller's own report. Returns True when a row was removed."""
    if (hf_user_id is None) == (anon_token is None):
        raise ValueError("exactly one of hf_user_id / anon_token must be set")
    col = "hf_user_id" if hf_user_id is not None else "anon_token"
    val = hf_user_id if hf_user_id is not None else anon_token
    cur = get_conn().execute(
        f"DELETE FROM ts_reports WHERE id = ? AND {col} = ?",
        (report_id, val),
    )
    return cur.rowcount > 0


def _current(
    slug: str,
    verse_key: str,
    category: str,
    tkey: str,
    hf_user_id: str | None,
    anon_token: str | None,
) -> dict[str, Any] | None:
    col = "hf_user_id" if hf_user_id is not None else "anon_token"
    val = hf_user_id if hf_user_id is not None else anon_token
    row = (
        get_conn()
        .execute(
            "SELECT * FROM ts_reports WHERE slug = ? AND verse_key = ? AND category = ? "
            f"AND target_key = ? AND {col} = ?",
            (slug, verse_key, category, tkey, val),
        )
        .fetchone()
    )
    return _row_to_dict(row) if row else None
