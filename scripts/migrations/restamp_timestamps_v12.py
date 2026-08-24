#!/usr/bin/env python3
"""One-time strict local restamp from timestamp shard v11 to native v12."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

import orjson

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qua_shared.timestamps_shards import brotli_shard  # noqa: E402
from qua_shared.timestamps_v12_audit import audit_v12_document  # noqa: E402


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="local directory of v11 <chapter>.json.gz files")
    parser.add_argument("output", type=Path, help="fresh local staging directory for v12 files")
    parser.add_argument("--summary", type=Path, help="write the audit summary as JSON")
    parser.add_argument("--require-chapters", type=int, default=114)
    return parser.parse_args()


def _files(root: Path) -> list[Path]:
    files = sorted(root.glob("*.json.gz"), key=lambda path: int(path.name.split(".", 1)[0]))
    if not files:
        raise SystemExit(f"no chapter shards found in {root}")
    return files


def _fresh_output(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if any(path.iterdir()):
        raise SystemExit(f"output directory must be empty: {path}")


def _restamp(path: Path) -> tuple[dict, bytes]:
    from qua_sdk.integrations.shards import restamp_v11_shard

    legacy = orjson.loads(gzip.decompress(path.read_bytes()))
    document = restamp_v11_shard(legacy)
    audit_v12_document(document)
    first = brotli_shard(document)
    second = brotli_shard(document)
    if first != second:
        raise RuntimeError(f"non-deterministic Brotli for {path.name}")
    return document, first


def _add(summary: Counter, document: dict, size: int) -> None:
    counts = audit_v12_document(document)
    summary.update(counts)
    summary["chapters"] += 1
    summary["brotli_bytes"] += size
    for reading in document["readings"]:
        verses = {part[0] for part in reading["parts"]}
        if len(verses) > 1:
            summary["cross_verse_readings"] += 1


def run(source: Path, output: Path, *, require_chapters: int) -> dict:
    files = _files(source)
    if require_chapters and len(files) != require_chapters:
        raise SystemExit(f"expected {require_chapters} chapters, found {len(files)}")
    _fresh_output(output)
    summary: Counter = Counter()
    versions: set[str] = set()
    for path in files:
        document, payload = _restamp(path)
        chapter = int(document["_meta"]["chapter"])
        if chapter != int(path.name.split(".", 1)[0]):
            raise RuntimeError(f"chapter/path mismatch in {path}")
        versions.add(str(document["_meta"]["phonemizer_version"]))
        (output / f"{chapter}.json.br").write_bytes(payload)
        _add(summary, document, len(payload))
    if len(versions) != 1 or next(iter(versions)).removesuffix(".0") != "2.14":
        raise RuntimeError(f"expected phonemizer 2.14, got {sorted(versions)}")
    return {"status": "ok", "phonemizer_versions": sorted(versions), **dict(summary)}


def main() -> int:
    args = _args()
    summary = run(
        args.input.resolve(), args.output.resolve(), require_chapters=args.require_chapters
    )
    rendered = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
