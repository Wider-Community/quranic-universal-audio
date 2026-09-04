"""Canonical timing projection from native timestamp shard v13 documents."""

from __future__ import annotations

from collections import defaultdict

from qua_shared.timestamps_codec import decode_document


def _index(ref: str) -> int:
    return int(ref.rsplit(":", 1)[1])


def _reading_segments(reading: dict) -> list[dict]:
    result = reading["analysis"]["result"]
    words = {int(row["id"]): row for row in result["words"]}
    word_times = {int(row["word_id"]): row for row in reading["timing"]["words"]}
    tokens_by_word: dict[int, list[dict]] = defaultdict(list)
    for token in reading["timing"]["animation_tokens"]:
        tokens_by_word[int(token["word_id"])].append(token)

    out = []
    for part in reading["parts"]:
        timed_words = []
        for word_id in part["word_ids"]:
            word = words[int(word_id)]
            timing = word_times[int(word_id)]
            letters = []
            for token in tokens_by_word[int(word_id)]:
                letters.append(
                    {
                        "source_unit_ids": list(map(int, token["source_unit_ids"])),
                        "text": token["text"],
                        "start_ms": token["start_ms"],
                        "end_ms": token["end_ms"],
                        "policy": token["policy"],
                    }
                )
            timed_words.append(
                {
                    "word_id": int(word_id),
                    "index": _index(word["ref"]),
                    "ref": word["ref"],
                    "start_ms": int(timing["start_ms"]),
                    "end_ms": int(timing["end_ms"]),
                    "letters": letters,
                }
            )
        out.append({"ref": part["ref"], "t": list(part["t"]), "words": timed_words})
    return out


def _split_occasions(segments: list[dict], foreign_starts: list[int]) -> list[list[dict]]:
    occasions: list[list[dict]] = []
    current: list[dict] = []
    for segment in segments:
        if current and any(current[-1]["t"][0] < at < segment["t"][0] for at in foreign_starts):
            occasions.append(current)
            current = []
        current.append(segment)
    if current:
        occasions.append(current)
    return occasions


def _coverage(segments: list[dict]) -> set[int]:
    return {word["index"] for segment in segments for word in segment["words"]}


def _completion(segments: list[dict], target: set[int]) -> int | None:
    covered: set[int] = set()
    for index, segment in enumerate(segments):
        covered |= _coverage([segment])
        if target <= covered:
            return index
    return None


def _canonical(occasions: list[list[dict]], target: set[int]) -> list[dict]:
    completing = [one for one in occasions if _completion(one, target) is not None]
    chosen = completing[0] if completing else max(occasions, key=lambda one: len(_coverage(one)))
    end = _completion(chosen, target)
    kept = chosen if end is None else chosen[: end + 1]
    restart = 0
    for index in range(1, len(kept)):
        words = kept[index]["words"]
        if words and words[0]["index"] == 1 and target <= _coverage(kept[index:]):
            restart = index
    return kept[restart:]


def _project(segments: list[dict]) -> dict:
    words = [word for segment in segments for word in segment["words"]]
    starts = [int(segment["t"][0]) for segment in segments]
    ends = [int(segment["t"][1]) for segment in segments]
    spans = []
    cursor = 0
    for segment in segments:
        count = len(segment["words"])
        if count:
            spans.append(
                {
                    "ref": segment["ref"],
                    "w_from": segment["words"][0]["index"],
                    "w_to": segment["words"][-1]["index"],
                    "occ_start": cursor,
                    "occ_end": cursor + count,
                    "start_ms": segment["words"][0]["start_ms"],
                    "end_ms": segment["words"][-1]["end_ms"],
                }
            )
        cursor += count
    for word in words:
        starts.append(word["start_ms"])
        ends.append(word["end_ms"])
        starts.extend(row["start_ms"] for row in word["letters"] if row["start_ms"] is not None)
        ends.extend(row["end_ms"] for row in word["letters"] if row["end_ms"] is not None)
    return {
        "words": words,
        "verse_start_ms": min(starts),
        "verse_end_ms": max(ends),
        "segments": spans,
    }


def project_native_shard(shard: dict) -> dict[str, dict]:
    """Select one canonical timing occasion per verse from a v13 shard."""
    if (shard.get("_meta") or {}).get("schema_version") != 13:
        raise ValueError("timestamp shard must use schema version 13")
    decoded = decode_document(shard)
    segments = [row for reading in decoded["readings"] for row in _reading_segments(reading)]
    segments.sort(key=lambda row: row["t"][0])
    by_ref: dict[str, list[dict]] = defaultdict(list)
    for segment in segments:
        by_ref[segment["ref"]].append(segment)
    starts = {ref: [row["t"][0] for row in rows] for ref, rows in by_ref.items()}
    out = {}
    for ref, rows in by_ref.items():
        foreign = sorted(at for other, values in starts.items() if other != ref for at in values)
        target = set(range(1, max(_coverage(rows), default=0) + 1))
        out[ref] = _project(_canonical(_split_occasions(rows, foreign), target))
    return out


def select_complete_verses(
    projected: dict[str, dict], word_counts: dict[tuple[int, int], int]
) -> tuple[dict[str, dict], list[str]]:
    """Return canonical verses containing every reference word index."""
    kept, dropped = {}, []
    for ref, verse in projected.items():
        chapter, ayah = map(int, ref.split(":", 1))
        expected = word_counts.get((chapter, ayah))
        covered = {word["index"] for word in verse.get("words") or []}
        if expected and not set(range(1, expected + 1)) <= covered:
            dropped.append(ref)
        else:
            kept[ref] = verse
    return kept, sorted(dropped)


__all__ = ["project_native_shard", "select_complete_verses"]
