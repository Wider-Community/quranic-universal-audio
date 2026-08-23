"""Resolve native v12 report targets and recheck their staleness."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

from config import TS_REPORT_BOUNDARY_STALE_MS
from services.storage import data_dir

logger = logging.getLogger(__name__)


def _load_shard(slug: str, chapter: int) -> dict[str, Any] | None:
    try:
        raw = data_dir.read_timestamps_chapter(slug, chapter)
        doc = json.loads(raw) if raw is not None else None
    except Exception:  # noqa: BLE001 - storage lookup is best effort during recheck
        logger.warning("native report shard read failed %s ch%s", slug, chapter)
        return None
    return (
        doc if isinstance(doc, dict) and doc.get("_meta", {}).get("schema_version") == 12 else None
    )


def _same_id(value: Any, target_id: str) -> bool:
    return str(value) == target_id


def _row(rows: Iterable[dict[str, Any]], key: str, target_id: str) -> dict[str, Any] | None:
    return next((row for row in rows if _same_id(row.get(key), target_id)), None)


def _reading(doc: dict[str, Any], target: dict[str, Any]) -> dict[str, Any] | None:
    reading_id = str(target.get("reading_id", ""))
    return next((row for row in doc.get("readings", []) if row.get("id") == reading_id), None)


def _cell_owners(reading: dict[str, Any]) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    view = reading["cells"]["cell_view"]
    for word in view.get("words", []):
        yield word, {"word_id": word["word_id"]}
    for boundary in view.get("boundaries", []):
        yield boundary, {"boundary_id": boundary["boundary_id"]}


def _group_key(group: dict[str, Any]) -> str:
    return ":".join(str(value) for value in group.get("column_ids", []))


def _native_entity(reading: dict[str, Any], kind: str, target_id: str) -> dict[str, Any] | None:
    result = reading["analysis"]["result"]
    if kind == "verse":
        parts = [part for part in reading.get("parts", []) if part.get("ref") == target_id]
        return {"ref": target_id, "parts": parts} if parts else None
    direct = {
        "word": (result.get("words", []), "id"),
        "sound": (result.get("sounds", []), "id"),
        "boundary": (result.get("boundaries", []), "id"),
    }
    if kind in direct:
        rows, key = direct[kind]
        entity = _row(rows, key, target_id)
        if entity is not None and kind == "word":
            return {**entity, "word_id": entity["id"]}
        return entity
    for owner, ownership in _cell_owners(reading):
        if kind == "column":
            entity = _row(owner.get("columns", []), "id", target_id)
        elif kind == "group":
            entity = next(
                (group for group in owner.get("groups", []) if _group_key(group) == target_id),
                None,
            )
        elif kind == "bridge":
            entity = _row(owner.get("bridges", []), "merger_id", target_id)
        else:
            return None
        if entity is not None:
            return {**entity, **ownership}
    return None


def _span(rows: Iterable[dict[str, Any]], key: str, target_id: str) -> tuple[int, int] | None:
    row = _row(rows, key, target_id)
    if row is None or row.get("start_ms") is None or row.get("end_ms") is None:
        return None
    return int(row["start_ms"]), int(row["end_ms"])


def _union(spans: Iterable[tuple[int, int] | None]) -> tuple[int, int] | None:
    present = [span for span in spans if span is not None]
    if not present:
        return None
    return min(span[0] for span in present), max(span[1] for span in present)


def _column_span(reading: dict[str, Any], column: dict[str, Any]) -> tuple[int, int] | None:
    timing = reading["timing"]
    unit_ids = {str(value) for value in column.get("source_unit_ids", [])}
    sound_ids = {
        str(value)
        for field in ("owned_sound_ids", "presented_sound_ids")
        for value in column.get(field, [])
    }
    return _union(
        [
            *(_span(timing.get("units", []), "source_unit_id", unit_id) for unit_id in unit_ids),
            *(_span(timing.get("sounds", []), "sound_id", sound_id) for sound_id in sound_ids),
        ]
    )


def _timing_span(
    reading: dict[str, Any], kind: str, target_id: str, native: dict[str, Any]
) -> tuple[int, int] | None:
    timing = reading["timing"]
    if kind == "verse":
        parts = native["parts"]
        return min(part["t"][0] for part in parts), max(part["t"][1] for part in parts)
    if kind == "word":
        return _span(timing.get("words", []), "word_id", target_id)
    if kind == "sound":
        return _span(timing.get("sounds", []), "sound_id", target_id)
    if kind == "boundary":
        return _span(timing.get("boundaries", []), "boundary_id", target_id)
    if kind == "bridge":
        sound = native.get("sound", {})
        return _span(timing.get("sounds", []), "sound_id", str(sound.get("sound_id")))
    if kind == "column":
        return _column_span(reading, native)
    if kind == "group":
        return _union(
            _span(timing.get("sounds", []), "sound_id", str(sound_id))
            for sound_id in native.get("sound_ids", [])
        )
    return None


def resolve_target(
    doc: dict[str, Any], verse_key: str, target: dict[str, Any]
) -> dict[str, Any] | None:
    """Return the exact native/timing fingerprint for ``target``."""
    if doc.get("_meta", {}).get("schema_version") != 12:
        return None
    reading = _reading(doc, target)
    if reading is None:
        return None
    kind = str(target.get("kind", ""))
    target_id = str(target.get("target_id", ""))
    native = _native_entity(reading, kind, target_id)
    if native is None:
        return None
    result = reading["analysis"]["result"]
    if kind == "verse" and target_id != verse_key:
        return None
    word_id = native.get("word_id")
    if word_id is not None:
        word = _row(result.get("words", []), "id", str(word_id))
        if word is None or ":".join(word["ref"].split(":")[:2]) != verse_key:
            return None
        native = {**native, "word_ref": word["ref"]}
    boundary_id = native.get("boundary_id")
    if boundary_id is None and kind == "boundary":
        boundary_id = native.get("id")
    if boundary_id is not None:
        boundary = _row(result.get("boundaries", []), "id", str(boundary_id))
        if boundary is None:
            return None
        adjacent = [boundary.get("before"), boundary.get("after")]
        refs = {
            ":".join(word["ref"].split(":")[:2])
            for value in adjacent
            if value is not None
            for word in result.get("words", [])
            if str(word.get("id")) == str(value)
        }
        if verse_key not in refs:
            return None
    span = _timing_span(reading, kind, target_id, native)
    return {
        "native_schema_version": 2,
        "shard_schema_version": 12,
        "native": native,
        "timing": None if span is None else {"start_ms": span[0], "end_ms": span[1]},
    }


def build_snapshot(slug: str, verse_key: str, target: dict[str, Any]) -> dict[str, Any] | None:
    try:
        chapter = int(verse_key.split(":", 1)[0])
    except (ValueError, IndexError):
        return None
    doc = _load_shard(slug, chapter)
    return resolve_target(doc, verse_key, target) if doc is not None else None


def _shifted(old: Any, new: Any) -> bool:
    return (
        isinstance(old, int)
        and isinstance(new, int)
        and abs(old - new) > TS_REPORT_BOUNDARY_STALE_MS
    )


def _timing_changed(report: dict[str, Any], old: dict[str, Any], new: dict[str, Any]) -> bool:
    before = old.get("timing") or {}
    after = new.get("timing") or {}
    if report.get("onset") and _shifted(before.get("start_ms"), after.get("start_ms")):
        return True
    return bool(report.get("offset") and _shifted(before.get("end_ms"), after.get("end_ms")))


def is_stale_after_restamp(report: dict[str, Any], doc: dict[str, Any]) -> bool:
    if report.get("category") == "audio":
        return False
    old = report.get("snapshot")
    new = resolve_target(doc, report["verse_key"], report.get("target") or {})
    if not old or new is None:
        return True
    if report.get("category") == "timing":
        return _timing_changed(report, old, new)
    return old.get("native") != new.get("native")


def _gap_present(snapshot: dict[str, Any] | None) -> bool:
    timing = (snapshot or {}).get("timing") or {}
    start, end = timing.get("start_ms"), timing.get("end_ms")
    return isinstance(start, int) and isinstance(end, int) and end > start


def _silence_action(report: dict[str, Any], doc: dict[str, Any]) -> tuple[str, str | None]:
    new = resolve_target(doc, report["verse_key"], report.get("target") or {})
    if new is None:
        return "stale", None
    present = _gap_present(new)
    subtype = report.get("subtype")
    if subtype == "pause_missed":
        return (
            ("resolve", "A pause now appears here on the latest timestamps.")
            if present
            else ("none", None)
        )
    if subtype == "pause_wasl":
        return (
            ("none", None)
            if present
            else ("resolve", "This pause is gone on the latest timestamps.")
        )
    if subtype == "pause_boundary":
        if not present:
            return "resolve", "This pause is gone on the latest timestamps."
        return (
            ("stale", None)
            if _timing_changed(report, report.get("snapshot") or {}, new)
            else ("none", None)
        )
    return "none", None


def recheck_reports_staleness(slug: str, affected_chapters: list[int] | None) -> int:
    from services.db import repo_ts_reports

    reports = repo_ts_reports.list_open_for_recheck(slug, chapters=affected_chapters)
    shards: dict[int, dict[str, Any] | None] = {}
    stale_ids: list[int] = []
    automatic: list[tuple[dict[str, Any], str]] = []
    for report in reports:
        chapter = report["chapter"]
        if chapter not in shards:
            shards[chapter] = _load_shard(slug, chapter)
        doc = shards[chapter]
        if doc is None:
            continue
        try:
            if report.get("category") == "silence":
                action, reason = _silence_action(report, doc)
                if action == "stale":
                    stale_ids.append(report["id"])
                elif action == "resolve" and reason:
                    automatic.append((report, reason))
            elif is_stale_after_restamp(report, doc):
                stale_ids.append(report["id"])
        except Exception:  # noqa: BLE001 - one report must not abort the batch
            logger.exception("staleness recheck failed for report %s", report.get("id"))
    _auto_resolve_silence(slug, automatic)
    return repo_ts_reports.mark_stale(stale_ids)


def _auto_resolve_silence(slug: str, rows: list[tuple[dict[str, Any], str]]) -> None:
    from services.db import repo_ts_reports
    from services.notifications import emit as notify

    for report, reason in rows:
        resolved = repo_ts_reports.resolve_auto(report_id=report["id"], reason=reason)
        if resolved is None:
            continue
        notify.notify_ts_report_auto_resolved(
            slug=slug,
            verse_key=resolved["verse_key"],
            category=resolved["category"],
            reporter_id=resolved["hf_user_id"],
            author_login=resolved["login_at_time"],
            report_id=resolved["id"],
            reason=reason,
        )
