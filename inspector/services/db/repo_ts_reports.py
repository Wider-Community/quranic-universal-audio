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

``delete`` is a SOFT delete: it stamps ``hidden_at`` so the report drops out of
every user-facing read (counts, verse lists, ``mine``, stale-recheck) while the
row is retained internally. Re-filing the same category+target un-hides the row.

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


def target_key(target: dict[str, Any], category: str = "", subtype: str | None = None) -> str:
    """Canonical key for a target descriptor (NULLs as empty), for ON CONFLICT.

    ``kind:word_index:source_letter_index:cell_index:phoneme_flat_index:share_group``,
    with ``:subtype`` appended for ``tajweed`` only — a tajweed report is unique per
    cell PER subtype (the same cell can carry both a ``wrong_rule`` and a
    ``missing_rule`` report), whereas timing/audio/other stay one-per-target.
    """

    def _s(v: Any) -> str:
        return "" if v is None else str(v)

    parts = [
        str(target.get("kind", "")),
        _s(target.get("word_index")),
        _s(target.get("source_letter_index")),
        _s(target.get("cell_index")),
        _s(target.get("phoneme_flat_index")),
        _s(target.get("share_group")),
    ]
    if category == "tajweed":
        parts.append(_s(subtype))
    return ":".join(parts)


def word_group_key(slug: str, verse_key: str, word_index: int, category: str) -> str:
    """Stable identity for a word-group (``timing`` + ``phonemes``) — the
    notification ``source_key`` that coalesces every cell/phoneme flagged in one
    word into a single owner alert."""
    return f"tsreport:{slug}:{verse_key}:{word_index}:{category}"


#: Report categories that are NOT publicly visible — only the reporter and a
#: ``view_nonpublic_reports`` holder see these grid flags (timing + the
#: verse-level audio/other/mapping reports stay public).
_NONPUBLIC_CATEGORIES = ("tajweed", "phonemes")


def _visibility_filter(
    hf_user_id: str | None, anon_token: str | None, can_view_nonpublic: bool
) -> tuple[str, list[Any]]:
    """SQL fragment restricting non-public reports to the reporter.

    ``tajweed`` + ``phonemes`` flags are visible only to the reporter (matched by
    ``hf_user_id`` or ``anon_token``) or to a caller holding the view-nonpublic
    capability; every other category stays public. Returns ``("", [])`` when no
    gating applies (``can_view_nonpublic`` or an internal all-rows read)."""
    if can_view_nonpublic:
        return "", []
    mine = ""
    params: list[Any] = []
    if hf_user_id is not None:
        mine = " OR hf_user_id = ?"
        params.append(hf_user_id)
    elif anon_token is not None:
        mine = " OR anon_token = ?"
        params.append(anon_token)
    placeholders = ",".join(f"'{c}'" for c in _NONPUBLIC_CATEGORIES)
    return f" AND (category NOT IN ({placeholders}){mine})", params


def _row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "slug": row["slug"],
        "verse_key": row["verse_key"],
        "chapter": row["chapter"],
        "category": row["category"],
        "subtype": row["subtype"],
        "onset": row["timing_onset"],
        "offset": row["timing_offset"],
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
            "onset_ms": row["snap_onset_ms"],
            "offset_ms": row["snap_offset_ms"],
        },
        "comment": row["comment"],
        "selected_rule_tags": _serde.json_loads(row["selected_rule_tags"]) or [],
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


def verse_counts(
    slug: str,
    *,
    hf_user_id: str | None = None,
    anon_token: str | None = None,
    can_view_nonpublic: bool = True,
) -> list[dict[str, Any]]:
    """Per-verse open/resolved counts for a reciter, ordered by verse. Feeds the
    reported-verses accordion (verse pills + count badges). The viewer context
    (defaulting to an all-rows internal read) hides non-public tajweed/phoneme
    counts from non-reporters — see ``_visibility_filter``."""
    vis_sql, vis_params = _visibility_filter(hf_user_id, anon_token, can_view_nonpublic)
    rows = (
        get_conn()
        .execute(
            "SELECT verse_key, "
            "SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_count, "
            "SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) AS resolved_count "
            "FROM ts_reports WHERE slug = ? AND hidden_at IS NULL" + vis_sql + " "
            "GROUP BY verse_key ORDER BY verse_key",
            (slug, *vis_params),
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


def list_for_verse(
    slug: str,
    verse_key: str,
    *,
    hf_user_id: str | None = None,
    anon_token: str | None = None,
    can_view_nonpublic: bool = True,
) -> list[dict[str, Any]]:
    """Every visible report on a verse (all identities + statuses), oldest first.
    The viewer context (defaulting to an all-rows internal read) hides non-public
    tajweed/phoneme reports from non-reporters — see ``_visibility_filter``."""
    vis_sql, vis_params = _visibility_filter(hf_user_id, anon_token, can_view_nonpublic)
    rows = (
        get_conn()
        .execute(
            "SELECT * FROM ts_reports WHERE slug = ? AND verse_key = ? AND hidden_at IS NULL"
            + vis_sql
            + " ORDER BY created_at, id",
            (slug, verse_key, *vis_params),
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
            f"SELECT * FROM ts_reports WHERE slug = ? AND {col} = ? AND hidden_at IS NULL "
            "ORDER BY created_at DESC, id DESC",
            (slug, val),
        )
        .fetchall()
    )
    return [_row_to_dict(r) for r in rows]


def get(report_id: int) -> dict[str, Any] | None:
    row = (
        get_conn()
        .execute("SELECT * FROM ts_reports WHERE id = ? AND hidden_at IS NULL", (report_id,))
        .fetchone()
    )
    return _row_to_dict(row) if row else None


def list_open_for_recheck(slug: str, *, chapters: list[int] | None) -> list[dict[str, Any]]:
    """Open, not-yet-stale reports for a slug, optionally scoped to ``chapters``.

    Drives the post-regeneration staleness recheck. ``chapters=None`` returns
    every open report for the slug (full/unknown-scope regen)."""
    if chapters is not None and not chapters:
        return []
    sql = (
        "SELECT * FROM ts_reports "
        "WHERE slug = ? AND status = 'open' AND stale = 0 AND hidden_at IS NULL"
    )
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
    onset: str | None = None,
    offset: str | None = None,
    selected_rule_tags: list[str] | None = None,
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
    tkey = target_key(target, category, subtype)
    snap = snapshot or {}
    # A hidden row still occupies the unique slot (so the upsert un-hides it),
    # but re-surfacing it counts as a NEW report for the notify-on-create path.
    created = (
        _current(slug, verse_key, category, tkey, hf_user_id, anon_token, visible_only=True) is None
    )
    ts = _serde.to_iso(at or _serde.now())
    conflict_col = "hf_user_id" if hf_user_id is not None else "anon_token"
    get_conn().execute(
        "INSERT INTO ts_reports("
        " slug, verse_key, chapter, category, subtype, timing_onset, timing_offset,"
        " target_kind, word_index, source_letter_index, cell_index, phoneme_flat_index,"
        " share_group, target_key,"
        " snap_chars, snap_role, snap_status, snap_tag, snap_secondary_tags,"
        " snap_phoneme_rule_tags, snap_phones, snap_share_group, snap_word_text,"
        " snap_verse_text, snap_schema_version, snap_onset_ms, snap_offset_ms,"
        " hf_user_id, anon_token, login_at_time, role_at_time, comment, selected_rule_tags,"
        " status, stale, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?, ?,?,?,?,?, ?,?, ?,?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?,?,?, 'open',0,?,?)"
        f" ON CONFLICT(slug, verse_key, category, target_key, {conflict_col})"
        f" WHERE {conflict_col} IS NOT NULL DO UPDATE SET"
        "   subtype = excluded.subtype,"
        "   timing_onset = excluded.timing_onset, timing_offset = excluded.timing_offset,"
        "   selected_rule_tags = excluded.selected_rule_tags,"
        "   snap_chars = excluded.snap_chars, snap_role = excluded.snap_role,"
        "   snap_status = excluded.snap_status, snap_tag = excluded.snap_tag,"
        "   snap_secondary_tags = excluded.snap_secondary_tags,"
        "   snap_phoneme_rule_tags = excluded.snap_phoneme_rule_tags,"
        "   snap_phones = excluded.snap_phones, snap_share_group = excluded.snap_share_group,"
        "   snap_word_text = excluded.snap_word_text, snap_verse_text = excluded.snap_verse_text,"
        "   snap_schema_version = excluded.snap_schema_version,"
        "   snap_onset_ms = excluded.snap_onset_ms, snap_offset_ms = excluded.snap_offset_ms,"
        "   comment = excluded.comment, updated_at = excluded.updated_at,"
        "   hidden_at = NULL",
        (
            slug,
            verse_key,
            chapter_of(verse_key),
            category,
            subtype,
            onset,
            offset,
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
            snap.get("onset_ms"),
            snap.get("offset_ms"),
            hf_user_id,
            anon_token,
            login_at_time,
            role_at_time,
            comment,
            _serde.json_dumps(selected_rule_tags) if selected_rule_tags else None,
            ts,
            ts,
        ),
    )
    row = _current(slug, verse_key, category, tkey, hf_user_id, anon_token)
    assert row is not None  # just inserted/updated
    return row, created


def create_many(
    *,
    slug: str,
    verse_key: str,
    items: list[dict[str, Any]],
    hf_user_id: str | None,
    anon_token: str | None,
    login_at_time: str | None,
    role_at_time: str | None,
    at: datetime | None = None,
) -> list[tuple[dict[str, Any], bool]]:
    """Insert/upsert every staged annotation for one identity on one verse,
    inside the caller's transaction. Each ``items`` entry is
    ``{category, subtype|onset/offset, target, snapshot, comment, selected_rule_tags}``.
    Returns ``[(row, created), ...]`` in input order (the route folds the
    ``created`` rows into grouped notifications). One shared timestamp keeps a
    batch's rows co-created for clean word-grouping."""
    if (hf_user_id is None) == (anon_token is None):
        raise ValueError("exactly one of hf_user_id / anon_token must be set")
    ts = at or _serde.now()
    out: list[tuple[dict[str, Any], bool]] = []
    for it in items:
        out.append(
            create(
                slug=slug,
                verse_key=verse_key,
                category=it["category"],
                subtype=it.get("subtype"),
                onset=it.get("onset"),
                offset=it.get("offset"),
                target=it["target"],
                snapshot=it.get("snapshot"),
                comment=it.get("comment"),
                hf_user_id=hf_user_id,
                anon_token=anon_token,
                login_at_time=login_at_time,
                role_at_time=role_at_time,
                selected_rule_tags=it.get("selected_rule_tags"),
                at=ts,
            )
        )
    return out


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
        " WHERE id = ? AND status = 'open' AND hidden_at IS NULL",
        (resolver_hf_user_id, resolver_login, resolver_comment, ts, ts, report_id),
    )
    if cur.rowcount == 0:
        return None
    return get(report_id)


def resolve_group(
    *,
    slug: str,
    verse_key: str,
    word_index: int,
    category: str,
    resolver_hf_user_id: str | None,
    resolver_login: str | None,
    resolver_comment: str | None,
    at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Resolve every open, visible row in a timing word-group as a unit.

    Group = all rows on ``(slug, verse_key, word_index, category)`` across ALL
    identities — owner resolution closes the word's timing issue regardless of
    who filed which cell. Returns the updated rows (the route fans one
    notification per distinct reporter), or ``[]`` when nothing was open."""
    if resolver_hf_user_id is not None:
        repo_access.ensure_user(resolver_hf_user_id)
    conn = get_conn()
    ids = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM ts_reports WHERE slug = ? AND verse_key = ? AND word_index = ? "
            "AND category = ? AND status = 'open' AND hidden_at IS NULL",
            (slug, verse_key, word_index, category),
        ).fetchall()
    ]
    if not ids:
        return []
    ts = _serde.to_iso(at or _serde.now())
    placeholders = ",".join("?" for _ in ids)
    conn.execute(
        f"UPDATE ts_reports SET status = 'resolved', resolved_by_hf_user_id = ?, "
        f"resolved_by_login = ?, resolver_comment = ?, resolved_at = ?, updated_at = ? "
        f"WHERE id IN ({placeholders})",
        (resolver_hf_user_id, resolver_login, resolver_comment, ts, ts, *ids),
    )
    rows = conn.execute(
        f"SELECT * FROM ts_reports WHERE id IN ({placeholders}) ORDER BY id", ids
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


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


def delete(
    *, report_id: int, hf_user_id: str | None, anon_token: str | None, at: datetime | None = None
) -> bool:
    """Soft-delete the caller's own report — stamp ``hidden_at`` so it drops out
    of every view while the row is retained internally. Returns True when a
    visible row was hidden (idempotent: a re-delete of an already-hidden row
    returns False)."""
    if (hf_user_id is None) == (anon_token is None):
        raise ValueError("exactly one of hf_user_id / anon_token must be set")
    col = "hf_user_id" if hf_user_id is not None else "anon_token"
    val = hf_user_id if hf_user_id is not None else anon_token
    ts = _serde.to_iso(at or _serde.now())
    cur = get_conn().execute(
        f"UPDATE ts_reports SET hidden_at = ?, updated_at = ? "
        f"WHERE id = ? AND {col} = ? AND hidden_at IS NULL",
        (ts, ts, report_id, val),
    )
    return cur.rowcount > 0


def _current(
    slug: str,
    verse_key: str,
    category: str,
    tkey: str,
    hf_user_id: str | None,
    anon_token: str | None,
    *,
    visible_only: bool = False,
) -> dict[str, Any] | None:
    col = "hf_user_id" if hf_user_id is not None else "anon_token"
    val = hf_user_id if hf_user_id is not None else anon_token
    sql = (
        "SELECT * FROM ts_reports WHERE slug = ? AND verse_key = ? AND category = ? "
        f"AND target_key = ? AND {col} = ?"
    )
    if visible_only:
        sql += " AND hidden_at IS NULL"
    row = get_conn().execute(sql, (slug, verse_key, category, tkey, val)).fetchone()
    return _row_to_dict(row) if row else None
