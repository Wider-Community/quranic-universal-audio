"""Strict identity-closure audit for compact timestamp shard v12."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from qua_shared.schemas.bucket.ts_shard import TsShardDoc


class V12AuditError(ValueError):
    pass


def _exact(label: str, actual: Iterable[int], expected: set[int]) -> None:
    found = set(map(int, actual))
    if found != expected:
        raise V12AuditError(f"{label} closure mismatch: {sorted(found ^ expected)[:10]}")


def _subset(label: str, actual: Iterable[int], expected: set[int]) -> None:
    missing = set(map(int, actual)) - expected
    if missing:
        raise V12AuditError(f"{label} has unknown ids: {sorted(missing)[:10]}")


def _sound_refs(row: list) -> tuple[int, list[int], list[int]]:
    return int(row[0]), list(map(int, row[1])), list(map(int, row[2]))


def _columns(owners: list[list], *, word: bool) -> list[list]:
    return [column for owner in owners for column in owner[2 if word else 1]]


def _sounds(owners: list[list], *, word: bool) -> list[list]:
    return [sound for owner in owners for sound in owner[3 if word else 2]]


def _bridges(owners: list[list], *, word: bool) -> list[list]:
    return [bridge for owner in owners for bridge in owner[6 if word else 3]]


def _audit_reading(reading: dict[str, Any]) -> dict[str, int]:
    render = reading["render"]
    words, boundaries = render["w"], render["b"]
    known_words = set(range(len(words)))
    known_sounds = set(range(len(render["p"])))
    known_occurrences = set(range(len(render["r"])))
    columns = [*_columns(words, word=True), *_columns(boundaries, word=False)]
    column_ids = [int(row[0]) for row in columns]
    if len(column_ids) != len(set(column_ids)):
        raise V12AuditError("duplicate compact column id")
    known_columns = set(column_ids)

    sounds = [*_sounds(words, word=True), *_sounds(boundaries, word=False)]
    bridges = [*_bridges(words, word=True), *_bridges(boundaries, word=False)]
    referenced_sounds: list[int] = []
    for row in [*sounds, *(bridge[3] for bridge in bridges)]:
        sound_id, attached, occurrences = _sound_refs(row)
        referenced_sounds.append(sound_id)
        _subset("cell sound columns", attached, known_columns)
        _subset("cell sound occurrences", occurrences, known_occurrences)
    _exact("cell sounds", referenced_sounds, known_sounds)

    for column in columns:
        _subset("column attachment", [] if column[6] is None else [column[6]], known_columns)
        _subset("column sounds", [*column[10], *column[11]], known_sounds)
        _subset("column occurrences", column[12], known_occurrences)
        silence = column[13]
        if isinstance(silence, int) and silence >= 0:
            _subset("column silence", [silence], known_occurrences)
    for word in words:
        for group in word[4]:
            _subset("group columns", group[2], known_columns)
            _subset("group sounds", group[3], known_sounds)
        for run in word[5]:
            _subset("run columns", run[2], known_columns)
    for bridge in bridges:
        _subset("bridge before columns", bridge[1], known_columns)
        _subset("bridge after columns", bridge[2], known_columns)

    timing = reading["timing"]
    if len(timing["w"]) != len(words) or len(timing["s"]) != len(render["p"]):
        raise V12AuditError("positional timing count mismatch")
    letter_ids = [int(row[0]) for row in timing["l"]]
    if len(letter_ids) != len(set(letter_ids)):
        raise V12AuditError("duplicate letter unit id")
    _subset("letter words", (row[1] for row in timing["l"]), known_words)
    _subset("column timing overrides", (row[0] for row in timing["c"]), known_columns)

    part_words = [
        word_id
        for _, _, _, first, count in reading["parts"]
        for word_id in range(int(first), int(first) + int(count))
    ]
    _exact("part words", part_words, known_words)
    return {
        "words": len(words),
        "sounds": len(render["p"]),
        "units": len(letter_ids),
        "boundaries": len(boundaries) + (1 if words else 0),
    }


def audit_v12_document(document: dict[str, Any]) -> dict[str, int]:
    """Validate schema plus every compact renderer/timing identity reference."""
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
