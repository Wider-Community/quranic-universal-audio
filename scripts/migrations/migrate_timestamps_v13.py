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
from pathlib import Path

import brotli
import orjson

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from qua_sdk.integrations.shard_audit import audit_v13_document as audit_sdk_v13  # noqa: E402
from qua_sdk.integrations.shards import restamp_v12_shard  # noqa: E402

from qua_shared.timestamps_shards import write_validated_shard  # noqa: E402
from qua_shared.timestamps_v13_audit import audit_v13_document  # noqa: E402


class MigrationInvariantError(ValueError):
    pass


def _load(path: Path) -> dict:
    return orjson.loads(brotli.decompress(path.read_bytes()))


def _assert_preserved(old: dict, new: dict, path: Path) -> None:
    old_meta, new_meta = old["_meta"], new["_meta"]
    for key, value in old_meta.items():
        if key not in {"schema_version", "phonemizer_version", "native_profile"}:
            if new_meta.get(key) != value:
                raise MigrationInvariantError(f"{path}: metadata drift at {key}")
    if len(old["readings"]) != len(new["readings"]):
        raise MigrationInvariantError(f"{path}: reading count changed")
    for index, (before, after) in enumerate(zip(old["readings"], new["readings"], strict=True)):
        if before["id"] != after["id"] or before["parts"] != after["parts"]:
            raise MigrationInvariantError(f"{path}: reading {index} identity/parts changed")
        if before["render"]["m"][0] != after["render"]["m"][0]:
            raise MigrationInvariantError(f"{path}: reading {index} render ref changed")
        if before["render"]["p"] != after["render"]["p"]:
            raise MigrationInvariantError(f"{path}: reading {index} sound tokens changed")
        old_words = [(row[0], row[1]) for row in before["render"]["w"]]
        new_words = [(row[0], row[1]) for row in after["render"]["w"]]
        if old_words != new_words:
            raise MigrationInvariantError(f"{path}: reading {index} word text/identity changed")
        old_boundaries = [(row[0], row[4], row[5]) for row in before["render"]["b"]]
        new_boundaries = [(row[0], row[4], row[5]) for row in after["render"]["b"]]
        if old_boundaries != new_boundaries:
            raise MigrationInvariantError(f"{path}: reading {index} boundary semantics changed")
        for key in ("w", "s", "c"):
            if before["timing"][key] != after["timing"][key]:
                raise MigrationInvariantError(f"{path}: reading {index} timing.{key} changed")


def migrate_tree(source: Path, destination: Path, *, replace: bool = False) -> dict:
    files = sorted(path for path in source.rglob("*.json.br") if path.is_file())
    if not files:
        raise FileNotFoundError(f"no .json.br shards under {source}")
    totals = Counter(files=0, readings=0, tokens=0, v12_bytes=0, v13_bytes=0)
    chapters: Counter[int] = Counter()
    for path in files:
        old = _load(path)
        if (old.get("_meta") or {}).get("schema_version") != 12:
            raise MigrationInvariantError(f"{path}: expected schema v12")
        relative = path.relative_to(source)
        target = destination / relative
        if target.exists() and not replace:
            raise FileExistsError(f"refusing existing output {target}; pass --replace")
        new = restamp_v12_shard(old)
        _assert_preserved(old, new, path)
        sdk_counts = audit_sdk_v13(new)
        site_counts = audit_v13_document(new)
        if sdk_counts != site_counts:
            raise MigrationInvariantError(f"{path}: SDK/site audit totals differ")
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
        chapters[int(new["_meta"]["chapter"])] += 1
    return {
        **dict(totals),
        "chapter_counts": dict(sorted(chapters.items())),
        "source": str(source.resolve()),
        "destination": str(destination.resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n", 1)[0])
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = migrate_tree(args.source, args.destination, replace=args.replace)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
