#!/usr/bin/env python3
"""Strictly restamp a local tree of compact timestamp shards from v12 to v13.

The input and output roots may contain either ``<slug>/timestamps/<chapter>.json.br``
or a single reciter's ``timestamps/<chapter>.json.br`` layout.  Existing output
files are refused unless ``--replace`` is explicit.  This command never accesses
or writes a bucket.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import brotli
import orjson

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from qua_sdk.integrations.native import analyse_native  # noqa: E402
from qua_sdk.integrations.shard_audit import audit_v13_document as audit_sdk_v13  # noqa: E402
from qua_sdk.integrations.shards import restamp_v12_shard  # noqa: E402

from qua_shared.timestamps_shards import write_validated_shard  # noqa: E402
from qua_shared.timestamps_v13_audit import audit_v13_document  # noqa: E402


class MigrationInvariantError(ValueError):
    pass


_POLICIES = ("timed", "cohighlight_previous", "cohighlight_next")


def _load(path: Path) -> dict:
    return orjson.loads(brotli.decompress(path.read_bytes()))


def _sound_change(before: dict, after: dict, path: Path, index: int) -> dict | None:
    old_tokens = list(map(str, before["render"]["p"]))
    new_tokens = list(map(str, after["render"]["p"]))
    if old_tokens == new_tokens:
        return None
    operations = []
    matcher = SequenceMatcher(a=old_tokens, b=new_tokens, autojunk=False)
    for tag, old_at, old_end, new_at, new_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        operations.append(
            {
                "kind": tag,
                "before": old_tokens[old_at:old_end],
                "after": new_tokens[new_at:new_end],
            }
        )
    return {
        "path": str(path),
        "reading_index": index,
        "parts": [str(row[0]) for row in before["parts"]],
        "before_count": len(old_tokens),
        "after_count": len(new_tokens),
        "operations": operations,
        "sound_timing_changed": before["timing"]["s"] != after["timing"]["s"],
        "cell_timing_changed": before["timing"]["c"] != after["timing"]["c"],
    }


def _assert_preserved(old: dict, new: dict, path: Path) -> list[dict]:
    old_meta, new_meta = old["_meta"], new["_meta"]
    for key, value in old_meta.items():
        if key not in {"schema_version", "phonemizer_version", "native_profile"}:
            if new_meta.get(key) != value:
                raise MigrationInvariantError(f"{path}: metadata drift at {key}")
    if len(old["readings"]) != len(new["readings"]):
        raise MigrationInvariantError(f"{path}: reading count changed")
    changes = []
    for index, (before, after) in enumerate(zip(old["readings"], new["readings"], strict=True)):
        if before["id"] != after["id"] or before["parts"] != after["parts"]:
            raise MigrationInvariantError(f"{path}: reading {index} identity/parts changed")
        if before["render"]["m"][0] != after["render"]["m"][0]:
            raise MigrationInvariantError(f"{path}: reading {index} render ref changed")
        sound_change = _sound_change(before, after, path, index)
        old_words = [(row[0], row[1]) for row in before["render"]["w"]]
        new_words = [(row[0], row[1]) for row in after["render"]["w"]]
        if old_words != new_words:
            raise MigrationInvariantError(f"{path}: reading {index} word text/identity changed")
        old_boundaries = [(row[0], row[4], row[5]) for row in before["render"]["b"]]
        new_boundaries = [(row[0], row[4], row[5]) for row in after["render"]["b"]]
        if old_boundaries != new_boundaries:
            raise MigrationInvariantError(f"{path}: reading {index} boundary semantics changed")
        if before["timing"]["w"] != after["timing"]["w"]:
            raise MigrationInvariantError(f"{path}: reading {index} timing.w changed")
        if sound_change is None:
            for key in ("s", "c"):
                if before["timing"][key] != after["timing"][key]:
                    raise MigrationInvariantError(f"{path}: reading {index} timing.{key} changed")
        else:
            old_sound_timing = before["timing"]["s"]
            new_sound_timing = after["timing"]["s"]
            if len(old_sound_timing) == len(new_sound_timing):
                if old_sound_timing != new_sound_timing:
                    raise MigrationInvariantError(
                        f"{path}: reading {index} one-to-one sound timing changed"
                    )
            elif (
                not old_sound_timing
                or not new_sound_timing
                or old_sound_timing[0][0] != new_sound_timing[0][0]
                or old_sound_timing[-1][1] != new_sound_timing[-1][1]
            ):
                raise MigrationInvariantError(
                    f"{path}: reading {index} changed-sound envelope drifted"
                )
            changes.append(sound_change)
    return changes


def migrate_tree(
    source: Path,
    destination: Path,
    *,
    replace: bool = False,
    resume: bool = False,
    chapter: int | None = None,
) -> dict:
    files = sorted(
        (path for path in source.rglob("*.json.br") if path.is_file()),
        # Keep the producer's bounded analysis cache useful across reciters:
        # equivalent readings from one chapter are migrated next to each other.
        key=lambda path: (int(path.name.removesuffix(".json.br")), str(path)),
    )
    if chapter is not None:
        files = [path for path in files if int(path.name.removesuffix(".json.br")) == chapter]
    if not files:
        suffix = f" for chapter {chapter}" if chapter is not None else ""
        raise FileNotFoundError(f"no .json.br shards under {source}{suffix}")
    totals = Counter(files=0, readings=0, tokens=0, v12_bytes=0, v13_bytes=0)
    chapters: Counter[int] = Counter()
    policies: Counter[str] = Counter()
    animation_texts: set[str] = set()
    sound_tokens: set[str] = set()
    sound_change_operations: Counter[str] = Counter()
    sound_count_deltas: Counter[int] = Counter()
    sound_change_examples: list[dict] = []
    changed_cell_timing_readings = 0
    active_chapter: int | None = None
    for file_number, path in enumerate(files, start=1):
        old = _load(path)
        if (old.get("_meta") or {}).get("schema_version") != 12:
            raise MigrationInvariantError(f"{path}: expected schema v12")
        chapter = int(old["_meta"]["chapter"])
        if active_chapter != chapter:
            # All reciters for a chapter are adjacent. Retain those native
            # projections across reciters, then release them before the next
            # chapter so the full-corpus migration stays memory-bounded.
            analyse_native.cache_clear()
            active_chapter = chapter
        relative = path.relative_to(source)
        target = destination / relative
        if target.exists() and not (replace or resume):
            raise FileExistsError(f"refusing existing output {target}; pass --replace or --resume")
        new = _load(target) if target.exists() and resume else restamp_v12_shard(old)
        sound_changes = _assert_preserved(old, new, relative)
        for change in sound_changes:
            sound_count_deltas[change["after_count"] - change["before_count"]] += 1
            changed_cell_timing_readings += int(change["cell_timing_changed"])
            for operation in change["operations"]:
                key = (
                    f"{operation['kind']}:"
                    f"{json.dumps(operation['before'], ensure_ascii=False)}->"
                    f"{json.dumps(operation['after'], ensure_ascii=False)}"
                )
                sound_change_operations[key] += 1
            if len(sound_change_examples) < 100:
                sound_change_examples.append(change)
        sdk_counts = audit_sdk_v13(new)
        site_counts = audit_v13_document(new)
        if sdk_counts != site_counts:
            raise MigrationInvariantError(f"{path}: SDK/site audit totals differ")
        if target.exists() and resume:
            payload = target.read_bytes()
        else:
            payload = write_validated_shard(target, new)
            if target.read_bytes() != payload:
                raise MigrationInvariantError(f"{target}: atomic write bytes differ")
        totals.update(
            files=1,
            readings=sdk_counts["readings"],
            tokens=sdk_counts["tokens"],
            v12_bytes=path.stat().st_size,
            v13_bytes=len(payload),
        )
        for reading in new["readings"]:
            sound_tokens.update(map(str, reading["render"]["p"]))
            for token in reading["render"]["a"]:
                animation_texts.add(str(token[4]))
                policies[_POLICIES[int(token[6])]] += 1
        chapters[chapter] += 1
        if file_number % 25 == 0 or file_number == len(files):
            print(f"migrated {file_number}/{len(files)} shards", file=sys.stderr, flush=True)
    return {
        **dict(totals),
        "chapter_counts": dict(sorted(chapters.items())),
        "animation_policy_counts": dict(sorted(policies.items())),
        "unique_animation_token_text_count": len(animation_texts),
        "unique_animation_token_texts": sorted(animation_texts),
        "unique_sound_token_count": len(sound_tokens),
        "unique_sound_tokens": sorted(sound_tokens),
        "phonemization_changes": {
            "reading_count": sum(sound_count_deltas.values()),
            "sound_count_deltas": {
                str(delta): count for delta, count in sorted(sound_count_deltas.items())
            },
            "operation_counts": dict(sorted(sound_change_operations.items())),
            "cell_timing_changed_readings": changed_cell_timing_readings,
            "examples": sound_change_examples,
        },
        "source": str(source.resolve()),
        "destination": str(destination.resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n", 1)[0])
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    output_policy = parser.add_mutually_exclusive_group()
    output_policy.add_argument("--replace", action="store_true")
    output_policy.add_argument("--resume", action="store_true")
    parser.add_argument("--chapter", type=int, choices=range(1, 115))
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = migrate_tree(
        args.source,
        args.destination,
        replace=args.replace,
        resume=args.resume,
        chapter=args.chapter,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if not args.quiet:
        print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
