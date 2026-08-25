"""Prepare the guarded v27 -> v28 report-target migration.

The v12 cutover originally required a pre-generated ``ts_report_v12_map``.
Production reached the v12 application code while its database was still v27,
so native report writes addressed columns that did not exist.  This preparer
reconstructs that map from the canonical verse-local positions retained by the
legacy rows and the already-active v12 shard.  Every stored text/status/timing
fingerprint is checked before a mapping is accepted; any drift aborts boot.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import unicodedata
from collections.abc import Callable
from typing import Any

from qua_shared.timestamps_codec import decode_document
from services.storage import data_dir

from .ts_target_snapshot import resolve_target

logger = logging.getLogger(__name__)

LEGACY_REPORT_SCHEMA_VERSION = 27
NATIVE_REPORT_SCHEMA_VERSION = 28

DocumentLoader = Callable[[str, int], dict[str, Any]]


class LegacyReportMappingError(RuntimeError):
    """A legacy target cannot be proven to name exactly one native target."""


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        is not None
    )


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _load_v12_document(slug: str, chapter: int) -> dict[str, Any]:
    raw = data_dir.read_timestamps_chapter(slug, chapter)
    if raw is None:
        raise LegacyReportMappingError(f"missing v12 shard for {slug} chapter {chapter}")
    try:
        encoded = json.loads(raw)
        doc = decode_document(encoded)
    except Exception as exc:  # noqa: BLE001 - converted to a cutover error with context
        raise LegacyReportMappingError(
            f"invalid v12 shard for {slug} chapter {chapter}: {exc}"
        ) from exc
    if doc.get("_meta", {}).get("schema_version") != 12:
        raise LegacyReportMappingError(f"non-v12 shard for {slug} chapter {chapter}")
    return doc


def _text_skeleton(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or "")).replace("ـ", "")
    return "".join(
        char
        for char in text
        if not unicodedata.combining(char) and unicodedata.category(char) not in {"Mn", "Me"}
    )


def _text_matches(old: object, new: object) -> bool:
    before, after = str(old or ""), str(new or "")
    if before == after:
        return True
    skeleton = _text_skeleton(before)
    return bool(skeleton) and skeleton == _text_skeleton(after)


def _same_span(row: sqlite3.Row, snapshot: dict[str, Any]) -> bool:
    old_start, old_end = row["snap_onset_ms"], row["snap_offset_ms"]
    if old_start is None or old_end is None:
        return True
    timing = snapshot.get("timing") or {}
    new_start, new_end = timing.get("start_ms"), timing.get("end_ms")
    if new_start is None or new_end is None:
        return False
    old_start, old_end = int(old_start), int(old_end)
    new_start, new_end = int(new_start), int(new_end)
    if old_start == old_end or new_start == new_end:
        return old_start == new_start and old_end == new_end
    return max(old_start, new_start) < min(old_end, new_end)


def _word_owner(reading: dict[str, Any], word_id: int) -> dict[str, Any]:
    owners = reading["cells"]["cell_view"].get("words", [])
    matches = [owner for owner in owners if int(owner["word_id"]) == word_id]
    if len(matches) != 1:
        raise LegacyReportMappingError(f"word {word_id} has {len(matches)} cell owners")
    return matches[0]


def _word_candidate(
    doc: dict[str, Any], verse_key: str, word_index: int
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    wanted_ref = f"{verse_key}:{word_index + 1}"
    matches: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for reading in doc.get("readings", []):
        for word in reading["analysis"]["result"].get("words", []):
            if word.get("ref") == wanted_ref:
                matches.append((reading, word, _word_owner(reading, int(word["id"]))))
    if len(matches) != 1:
        raise LegacyReportMappingError(f"{wanted_ref} resolved {len(matches)} native words")
    return matches[0]


def _validate_word(row: sqlite3.Row, word: dict[str, Any]) -> None:
    old_text = row["snap_word_text"]
    if old_text and not _text_matches(old_text, word.get("text")):
        raise LegacyReportMappingError(
            f"report {row['id']} word text drift: {old_text!r} != {word.get('text')!r}"
        )


def _validate_column(row: sqlite3.Row, column: dict[str, Any]) -> None:
    if row["snap_chars"] and not _text_matches(row["snap_chars"], column.get("text")):
        raise LegacyReportMappingError(
            f"report {row['id']} column text drift: {row['snap_chars']!r} != {column.get('text')!r}"
        )
    old_role = row["snap_role"]
    native_role = column.get("role")
    role_matches = (
        old_role is None
        or old_role == native_role
        or (old_role == "base" and native_role in {"letter", "madd"})
    )
    if not role_matches:
        raise LegacyReportMappingError(
            f"report {row['id']} column role drift: {old_role!r} != {native_role!r}"
        )
    if row["snap_status"] and row["snap_status"] != column.get("status"):
        raise LegacyReportMappingError(
            f"report {row['id']} column status drift: {row['snap_status']!r} != "
            f"{column.get('status')!r}"
        )


def _column_at(
    row: sqlite3.Row, owner: dict[str, Any], *, validate_snapshot: bool = True
) -> dict[str, Any]:
    index = row["cell_index"]
    columns = owner.get("columns", [])
    if index is None or not 0 <= int(index) < len(columns):
        raise LegacyReportMappingError(
            f"report {row['id']} column index {index!r} absent from native word"
        )
    column = columns[int(index)]
    if validate_snapshot:
        _validate_column(row, column)
    return column


def _target_for_word(
    row: sqlite3.Row,
    reading: dict[str, Any],
    word: dict[str, Any],
    owner: dict[str, Any],
) -> dict[str, str]:
    old_kind = str(row["target_kind"])
    if old_kind == "word":
        kind, target_id = "word", word["id"]
    elif old_kind == "gap":
        kind, target_id = "boundary", word.get("after_boundary_id")
    elif old_kind == "phoneme":
        index = row["phoneme_flat_index"]
        sound_ids = word.get("sound_ids", [])
        if index is None or not 0 <= int(index) < len(sound_ids):
            raise LegacyReportMappingError(
                f"report {row['id']} sound index {index!r} absent from native word"
            )
        kind, target_id = "sound", sound_ids[int(index)]
    elif old_kind == "cell":
        column = _column_at(row, owner)
        kind, target_id = "column", column["id"]
    elif old_kind == "cell_group":
        # A legacy group snapshot describes the whole group, not its anchoring
        # cell. Resolve the anchor position first, then validate concatenated
        # native group text below.
        column = _column_at(row, owner, validate_snapshot=False)
        groups = [group for group in owner.get("groups", []) if column["id"] in group["column_ids"]]
        if len(groups) != 1:
            raise LegacyReportMappingError(
                f"report {row['id']} column {column['id']} belongs to {len(groups)} groups"
            )
        group = groups[0]
        text_by_id = {column["id"]: column.get("text", "") for column in owner["columns"]}
        group_text = "".join(str(text_by_id.get(value, "")) for value in group["column_ids"])
        if row["snap_chars"] and not _text_matches(row["snap_chars"], group_text):
            raise LegacyReportMappingError(
                f"report {row['id']} group text drift: {row['snap_chars']!r} != {group_text!r}"
            )
        kind = "group"
        target_id = ":".join(str(value) for value in group["column_ids"])
    else:
        raise LegacyReportMappingError(f"unsupported legacy target kind {old_kind!r}")
    if target_id is None:
        raise LegacyReportMappingError(f"report {row['id']} has no native {kind} target")
    return {"reading_id": str(reading["id"]), "kind": kind, "target_id": str(target_id)}


def _verse_target(row: sqlite3.Row, doc: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
    candidates = []
    for reading in doc.get("readings", []):
        if not any(part.get("ref") == row["verse_key"] for part in reading.get("parts", [])):
            continue
        target = {
            "reading_id": str(reading["id"]),
            "kind": "verse",
            "target_id": str(row["verse_key"]),
        }
        snapshot = resolve_target(doc, str(row["verse_key"]), target)
        if snapshot is not None and _same_span(row, snapshot):
            candidates.append((target, snapshot))
    if len(candidates) != 1:
        raise LegacyReportMappingError(
            f"report {row['id']} verse resolved {len(candidates)} native targets"
        )
    return candidates[0]


def _map_row(row: sqlite3.Row, doc: dict[str, Any]) -> dict[str, Any]:
    if row["word_index"] is None:
        if row["target_kind"] != "verse":
            raise LegacyReportMappingError(f"report {row['id']} has no legacy word position")
        target, snapshot = _verse_target(row, doc)
    else:
        reading, word, owner = _word_candidate(doc, str(row["verse_key"]), int(row["word_index"]))
        _validate_word(row, word)
        target = _target_for_word(row, reading, word, owner)
        snapshot = resolve_target(doc, str(row["verse_key"]), target)
        if snapshot is None:
            raise LegacyReportMappingError(f"report {row['id']} target {target} did not resolve")
        if not _same_span(row, snapshot):
            raise LegacyReportMappingError(f"report {row['id']} timing span drift")
    suffix = str(row["subtype"] or "") if row["category"] == "tajweed" else ""
    key_parts = [target["reading_id"], target["kind"], target["target_id"]]
    if row["category"] == "tajweed":
        key_parts.append(suffix)
    return {
        "report_id": int(row["id"]),
        "reading_id": target["reading_id"],
        "target_kind": target["kind"],
        "target_id": target["target_id"],
        "target_key": ":".join(key_parts),
        "snapshot_json": json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
    }


def prepare_native_report_map(
    conn: sqlite3.Connection, *, load_document: DocumentLoader | None = None
) -> int:
    """Populate ``ts_report_v12_map`` for a v27 DB before migration 28.

    Returns the number of mapped legacy rows. Other schema versions and empty
    report tables are no-ops. A partial or ambiguous mapping raises and leaves
    the database untouched, so boot cannot expose v12 code over a v27 table.
    """

    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version != LEGACY_REPORT_SCHEMA_VERSION or not _table_exists(conn, "ts_reports"):
        return 0
    if {"reading_id", "target_id", "snapshot_json"}.issubset(_columns(conn, "ts_reports")):
        return 0

    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM ts_reports ORDER BY id").fetchall()
    if not rows:
        return 0
    expected_ids = {int(row["id"]) for row in rows}
    if _table_exists(conn, "ts_report_v12_map"):
        mapped_ids = {
            int(row[0]) for row in conn.execute("SELECT report_id FROM ts_report_v12_map")
        }
        if mapped_ids != expected_ids:
            raise LegacyReportMappingError(
                f"existing native report map covers {len(mapped_ids)} of {len(expected_ids)} rows"
            )
        return len(mapped_ids)

    loader = load_document or _load_v12_document
    cache: dict[tuple[str, int], dict[str, Any]] = {}
    mappings = []
    for row in rows:
        key = (str(row["slug"]), int(row["chapter"]))
        if key not in cache:
            cache[key] = loader(*key)
        mappings.append(_map_row(row, cache[key]))

    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "CREATE TABLE ts_report_v12_map ("
            "report_id INTEGER PRIMARY KEY, reading_id TEXT NOT NULL, "
            "target_kind TEXT NOT NULL, target_id TEXT NOT NULL, "
            "target_key TEXT NOT NULL, snapshot_json TEXT NOT NULL)"
        )
        conn.executemany(
            "INSERT INTO ts_report_v12_map VALUES "
            "(:report_id,:reading_id,:target_kind,:target_id,:target_key,:snapshot_json)",
            mappings,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    logger.info("prepared native targets for %d legacy timestamp reports", len(mappings))
    return len(mappings)


def assert_native_report_schema(conn: sqlite3.Connection) -> None:
    """Refuse a healthy boot when native report code sees a legacy table."""

    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    required = {"reading_id", "target_id", "snapshot_json"}
    present = _columns(conn, "ts_reports") if _table_exists(conn, "ts_reports") else set()
    missing = required - present
    if version < NATIVE_REPORT_SCHEMA_VERSION or missing:
        raise RuntimeError(
            "native timestamp reports require SQLite schema v28 with "
            f"{sorted(required)}; found v{version}, missing {sorted(missing)}"
        )
