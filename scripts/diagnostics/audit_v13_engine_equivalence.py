#!/usr/bin/env python3
"""Replay v12 timing through the batch-engine finalizer and prove v13 byte identity."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import brotli
import orjson

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from qua_sdk.integrations.native import analyse_native  # noqa: E402
from qua_timing_engine.timestamps.finalize import finalize_shards  # noqa: E402


class ReplayInvariantError(ValueError):
    pass


def _load_shard(path: Path) -> dict:
    return orjson.loads(brotli.decompress(path.read_bytes()))


def _match_segment(chapter: dict, part: list) -> int:
    candidates = [
        index
        for index, segment in enumerate(chapter.get("segments") or [])
        if int(segment.get("time_start", -1)) == int(part[1])
        and int(segment.get("time_end", -1)) == int(part[2])
    ]
    if len(candidates) != 1:
        raise ReplayInvariantError(
            f"{chapter.get('ref')}:{part[0]} [{part[1]}, {part[2]}] matched {candidates}"
        )
    return candidates[0]


def _result_words(
    reading: dict,
    part: list,
    *,
    include_sounds: bool,
    acoustic_tokens: list[str],
    sound_spans: list[list[int]],
) -> list[dict]:
    render, timing = reading["render"], reading["timing"]
    first, count = int(part[3]), int(part[4])
    letters: dict[int, list[list]] = defaultdict(list)
    for row in timing["l"]:
        letters[int(row[1])].append(row)
    words = []
    for word_id in range(first, first + count):
        meta, span = render["w"][word_id], timing["w"][word_id]
        words.append(
            {
                "location": meta[0],
                "start": (int(span[0]) - int(part[1])) / 1000,
                "end": (int(span[1]) - int(part[1])) / 1000,
                "letters": [
                    {
                        "char": row[2],
                        "start": (None if row[3] is None else (int(row[3]) - int(part[1])) / 1000),
                        "end": (None if row[4] is None else (int(row[4]) - int(part[1])) / 1000),
                    }
                    for row in letters.get(word_id, [])
                ],
                "phones": [],
            }
        )
    if include_sounds and words:
        words[0]["phones"] = [
            {
                "phone": token,
                "start": (int(span[0]) - int(part[1])) / 1000,
                "end": (int(span[1]) - int(part[1])) / 1000,
            }
            for token, span in zip(acoustic_tokens, sound_spans, strict=True)
        ]
    return words


def replay_results(
    detailed: dict, v12_root: Path, migrated_v13_root: Path
) -> tuple[dict[int, list[tuple[int, dict]]], dict]:
    chapters = detailed.get("entries") or []
    results: dict[int, list[tuple[int, dict]]] = defaultdict(list)
    shared_meta: dict | None = None
    for chapter_index, chapter in enumerate(chapters):
        chapter_number = int(chapter["ref"])
        document = _load_shard(v12_root / f"{chapter_number}.json.br")
        migrated = _load_shard(migrated_v13_root / f"{chapter_number}.json.br")
        if len(document["readings"]) != len(migrated["readings"]):
            raise ReplayInvariantError(f"chapter {chapter_number}: migrated reading count differs")
        meta = document["_meta"]
        provenance = {
            key: meta.get(key)
            for key in (
                "audio_category",
                "padding",
                "beam",
                "method",
                "aligner_model",
                "shared_cmvn",
                "audio_source",
                "created_at",
            )
        }
        if shared_meta is None:
            shared_meta = provenance
        elif provenance != shared_meta:
            raise ReplayInvariantError(f"chapter {chapter_number}: provenance differs")
        for reading, migrated_reading in zip(
            document["readings"], migrated["readings"], strict=True
        ):
            if reading["id"] != migrated_reading["id"]:
                raise ReplayInvariantError(f"chapter {chapter_number}: migrated reading ids differ")
            first_ref = reading["render"]["w"][0][0]
            last_ref = reading["render"]["w"][-1][0]
            reading_ref = first_ref if first_ref == last_ref else f"{first_ref}-{last_ref}"
            acoustic = analyse_native(reading_ref, display=False)
            acoustic_tokens = [sound.token for sound in acoustic.result.sounds]
            sound_spans = migrated_reading["timing"]["s"]
            if len(acoustic_tokens) != len(sound_spans):
                raise ReplayInvariantError(
                    f"{reading_ref}: producer/migrated sound counts differ "
                    f"({len(acoustic_tokens)} != {len(sound_spans)})"
                )
            for part_index, part in enumerate(reading["parts"]):
                segment_index = _match_segment(chapter, part)
                results[chapter_index].append(
                    (
                        segment_index,
                        {
                            "status": "ok",
                            "words": _result_words(
                                reading,
                                part,
                                include_sounds=part_index == 0,
                                acoustic_tokens=acoustic_tokens,
                                sound_spans=sound_spans,
                            ),
                            "wasl": part_index < len(reading["parts"]) - 1,
                        },
                    )
                )
    if shared_meta is None:
        raise ReplayInvariantError("no input shards")
    for rows in results.values():
        rows.sort(key=lambda row: row[0])
    return dict(results), shared_meta


def compare_trees(expected: Path, actual: Path) -> dict:
    expected_files = sorted(
        expected.glob("*.json.br"), key=lambda path: int(path.stem.split(".")[0])
    )
    actual_files = sorted(actual.glob("*.json.br"), key=lambda path: int(path.stem.split(".")[0]))
    if [path.name for path in expected_files] != [path.name for path in actual_files]:
        raise ReplayInvariantError("expected/actual shard file sets differ")
    mismatches = [
        left.name
        for left, right in zip(expected_files, actual_files, strict=True)
        if left.read_bytes() != right.read_bytes()
    ]
    if mismatches:
        raise ReplayInvariantError(f"compressed-byte mismatches: {mismatches[:10]}")
    return {
        "files": len(expected_files),
        "bytes": sum(path.stat().st_size for path in expected_files),
        "byte_identical": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("detailed", type=Path)
    parser.add_argument("v12_root", type=Path)
    parser.add_argument("migrated_v13_root", type=Path)
    parser.add_argument("engine_output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    detailed = json.loads(args.detailed.read_text(encoding="utf-8"))
    results, meta = replay_results(detailed, args.v12_root, args.migrated_v13_root)
    if args.engine_output.exists():
        raise FileExistsError(f"engine output must be a fresh path: {args.engine_output}")
    args.engine_output.mkdir(parents=True)
    temporary = Path(tempfile.mkdtemp(prefix="v13_replay_", dir=args.engine_output))
    finalize_shards(
        {int(meta["beam"]): results},
        chapters=detailed["entries"],
        canonical_beam=int(meta["beam"]),
        beams=[int(meta["beam"])],
        output_dir=args.engine_output,
        audio_category=str(meta["audio_category"]),
        audio_source=str(meta["audio_source"]),
        method=str(meta["method"]),
        shared_cmvn=bool(meta["shared_cmvn"]),
        padding=str(meta["padding"]),
        reciter=args.engine_output.name,
        refresh_chapters=None,
        aligner_model=str(meta["aligner_model"]),
        tmp_dir=temporary,
        created_at=str(meta["created_at"]),
    )
    report = {
        **compare_trees(args.migrated_v13_root, args.engine_output / "timestamps"),
        "chapters_in_detailed": len(detailed["entries"]),
        "aligned_chapters_replayed": len(results),
        "provenance": meta,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
