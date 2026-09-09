"""Strict identity-closure audit for compact timestamp shard v13."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from qua_shared.schemas.bucket.ts_shard import TsShardDoc


class V13AuditError(ValueError):
    pass


def _exact(label: str, actual: Iterable[int], expected: set[int]) -> None:
    found = set(map(int, actual))
    if found != expected:
        raise V13AuditError(f"{label} closure mismatch: {sorted(found ^ expected)[:10]}")


def _subset(label: str, actual: Iterable[int], expected: set[int]) -> None:
    missing = set(map(int, actual)) - expected
    if missing:
        raise V13AuditError(f"{label} has unknown ids: {sorted(missing)[:10]}")


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
        raise V13AuditError("duplicate compact column id")
    known_columns = set(column_ids)

    sounds = [*_sounds(words, word=True), *_sounds(boundaries, word=False)]
    bridges = [*_bridges(words, word=True), *_bridges(boundaries, word=False)]
    referenced_sounds: list[int] = []
    for row in [*sounds, *(bridge[3] for bridge in bridges)]:
        sound_id = int(row[0])
        referenced_sounds.append(sound_id)
        _subset("cell sound columns", row[1], known_columns)
        _subset("cell sound occurrences", row[2], known_occurrences)
    _exact("cell sounds", referenced_sounds, known_sounds)

    for column in columns:
        _subset("column attachment", [] if column[6] is None else [column[6]], known_columns)
        _subset("column sounds", [*column[10], *column[11]], known_sounds)
        _subset("column occurrences", column[12], known_occurrences)
        if isinstance(column[13], int) and column[13] >= 0:
            _subset("column silence", [column[13]], known_occurrences)
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
        raise V13AuditError("positional timing count mismatch")
    animation = render["a"]
    if len(timing["a"]) != len(animation):
        raise V13AuditError("animation timing count mismatch")
    for index, row in enumerate(animation):
        if len(row) != 8 or row[6] not in {0, 1, 2}:
            raise V13AuditError(f"animation token {index} has an invalid shape or policy")
    _subset("animation words", (row[0] for row in animation), known_words)
    _subset(
        "animation targets",
        (row[7] for row in animation if row[7] is not None),
        set(range(len(animation))),
    )
    _subset("animation sounds", (sound for row in animation for sound in row[5]), known_sounds)
    for index, (row, span) in enumerate(zip(animation, timing["a"], strict=True)):
        if not row[3] or not set(row[3]) <= set(row[2]):
            raise V13AuditError(f"animation token {index} has invalid paint characters")
        if span[0] is None or span[1] is None:
            raise V13AuditError(f"animation token {index} has no timing interval")
        target = row[7]
        if row[6] == 0 and target is not None:
            raise V13AuditError(f"timed animation token {index} has a target")
        if row[6] != 0 and (target is None or animation[int(target)][6] != 0):
            raise V13AuditError(f"co-highlight token {index} lacks a timed target")
        if target is not None and span != timing["a"][int(target)]:
            raise V13AuditError(f"co-highlight token {index} timing differs from its target")
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
        "tokens": len(animation),
        "boundaries": len(boundaries) + (1 if words else 0),
    }


def audit_v13_document(document: dict[str, Any]) -> dict[str, int]:
    """Validate schema plus every compact renderer/timing identity reference."""
    TsShardDoc.model_validate(document)
    totals: dict[str, int] = dict.fromkeys(
        ("readings", "parts", "words", "sounds", "tokens", "boundaries"), 0
    )
    for reading in document["readings"]:
        counts = _audit_reading(reading)
        totals["readings"] += 1
        totals["parts"] += len(reading["parts"])
        for key in ("words", "sounds", "tokens", "boundaries"):
            totals[key] += counts[key]
    return totals


__all__ = ["V13AuditError", "audit_v13_document"]
