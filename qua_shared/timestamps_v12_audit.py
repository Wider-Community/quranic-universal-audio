"""Strict identity-closure audit for native timestamp shard v12."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from qua_shared.schemas.bucket.ts_shard import TsShardDoc


class V12AuditError(ValueError):
    pass


def _ids(rows: Iterable[dict[str, Any]], key: str) -> set[int]:
    values = [int(row[key]) for row in rows]
    if len(values) != len(set(values)):
        raise V12AuditError(f"duplicate {key}")
    return set(values)


def _exact(label: str, actual: Iterable[int], expected: set[int]) -> None:
    found = set(map(int, actual))
    if found != expected:
        raise V12AuditError(f"{label} closure mismatch: {sorted(found ^ expected)[:10]}")


def _subset(label: str, actual: Iterable[int], expected: set[int]) -> None:
    missing = set(map(int, actual)) - expected
    if missing:
        raise V12AuditError(f"{label} has unknown ids: {sorted(missing)[:10]}")


def _audit_cells(reading: dict[str, Any], known: dict[str, set[int]]) -> None:
    view = reading["cells"]["cell_view"]
    owners = [*view.get("words", []), *view.get("boundaries", [])]
    columns = [column for owner in owners for column in owner.get("columns", [])]
    column_ids = _ids(columns, "id")
    _subset("cell words", (row["word_id"] for row in view.get("words", [])), known["words"])
    _subset(
        "cell boundaries",
        (row["boundary_id"] for row in view.get("boundaries", [])),
        known["boundaries"],
    )
    for column in columns:
        _subset("column source units", column.get("source_unit_ids", []), known["units"])
        _subset(
            "column sounds",
            [*column.get("owned_sound_ids", []), *column.get("presented_sound_ids", [])],
            known["sounds"],
        )
        attached = column.get("attached_to_column_id")
        _subset("column attachment", [] if attached is None else [attached], column_ids)
    for owner in owners:
        for sound in owner.get("sounds", []):
            _subset("cell sound", [sound["sound_id"]], known["sounds"])
            _subset("cell sound columns", sound.get("column_ids", []), column_ids)
        for group in owner.get("groups", []):
            _subset("group columns", group.get("column_ids", []), column_ids)
            _subset("group sounds", group.get("sound_ids", []), known["sounds"])
        for bridge in owner.get("bridges", []):
            _subset("bridge merger", [bridge["merger_id"]], known["mergers"])


def _audit_reading(reading: dict[str, Any]) -> dict[str, int]:
    result = reading["analysis"]["result"]
    source = reading["source"]["source"]
    known = {
        "words": _ids(result.get("words", []), "id"),
        "sounds": _ids(result.get("sounds", []), "id"),
        "boundaries": _ids(result.get("boundaries", []), "id"),
        "mergers": _ids(result.get("mergers", []), "id"),
        "units": _ids(source.get("units", []), "id"),
    }
    for word in result.get("words", []):
        _subset("word sounds", word.get("sound_ids", []), known["sounds"])
        _subset(
            "word boundaries",
            [word["before_boundary_id"], word["after_boundary_id"]],
            known["boundaries"],
        )
    _subset("sound words", (row["word_id"] for row in result.get("sounds", [])), known["words"])
    for unit in source.get("units", []):
        _subset("unit words", [unit["word_id"]], known["words"])
        _subset(
            "unit sounds",
            [*unit.get("owned_sound_ids", []), *unit.get("presented_sound_ids", [])],
            known["sounds"],
        )
    _audit_cells(reading, known)
    timing = reading["timing"]
    for row in timing["units"]:
        if (row["start_ms"] is None) != (row["end_ms"] is None):
            raise V12AuditError(f"source unit {row['source_unit_id']} has a half-null interval")
    _exact("timed words", (row["word_id"] for row in timing["words"]), known["words"])
    _exact("timed sounds", (row["sound_id"] for row in timing["sounds"]), known["sounds"])
    _exact("timed units", (row["source_unit_id"] for row in timing["units"]), known["units"])
    _exact(
        "timed boundaries",
        (row["boundary_id"] for row in timing["boundaries"]),
        known["boundaries"],
    )
    _exact(
        "part words", (one for part in reading["parts"] for one in part["word_ids"]), known["words"]
    )
    return {name: len(ids) for name, ids in known.items()}


def audit_v12_document(document: dict[str, Any]) -> dict[str, int]:
    """Validate schema plus every native/timing identity reference."""
    TsShardDoc.model_validate(document)
    totals = {key: 0 for key in ("readings", "parts", "words", "sounds", "units", "boundaries")}
    for reading in document["readings"]:
        counts = _audit_reading(reading)
        totals["readings"] += 1
        totals["parts"] += len(reading["parts"])
        for key in ("words", "sounds", "units", "boundaries"):
            totals[key] += counts[key]
    return totals


__all__ = ["V12AuditError", "audit_v12_document"]
