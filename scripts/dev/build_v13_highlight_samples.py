"""Build local v13 Nasser shards from the matching legacy timing fixtures."""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
from collections import defaultdict
from pathlib import Path

import brotli
from qua_sdk.integrations.shard_audit import audit_v13_document
from qua_sdk.integrations.shards import restamp_v11_shard

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "inspector/.fixtures/reciters/nasser_qatami_after_psil/timestamps"
OUTPUT = ROOT / ".local/v13-fixtures/reciters/nasser_qatami_after_psil/timestamps"
REFS = (
    "2:2",
    "2:3",
    "2:17",
    "2:22",
    "2:61",
    "2:72",
    "2:245",
    "4:1",
    "19:49",
    "19:58",
    "19:98",
    "21:88",
    "52:37",
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full",
        action="store_true",
        help="build all 114 complete chapter shards instead of the highlight samples",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="install a successfully audited full build into the inspector fixtures",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="reuse already-audited complete chapter outputs during a full build",
    )
    return parser.parse_args()


def _load(chapter: int) -> dict:
    with gzip.open(SOURCE / f"{chapter}.json.gz", "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _restamp(chapter: int, refs: set[str] | None) -> dict:
    source = _load(chapter)
    segments = source["segments"]
    if refs is not None:
        segments = [row for row in segments if row["ref"] in refs]
        missing = refs - {row["ref"] for row in segments}
        if missing:
            raise ValueError(f"chapter {chapter} lacks fixtures for {sorted(missing)}")
    legacy = {
        "_meta": {
            **source["_meta"],
            "schema_version": 11,
            "chapter": chapter,
        },
        "segments": segments,
    }
    document = restamp_v11_shard(legacy)
    document["_meta"]["fixture_source"] = "nasser_qatami_after_psil"
    if refs is not None:
        document["_meta"]["fixture_refs"] = sorted(refs)
    audit_v13_document(document)
    return document


def main() -> None:
    args = _args()
    if args.install and not args.full:
        raise SystemExit("--install requires --full")
    if args.resume and not args.full:
        raise SystemExit("--resume requires --full")

    refs_by_chapter: dict[int, set[str]] = defaultdict(set)
    for ref in REFS:
        refs_by_chapter[int(ref.split(":", 1)[0])].add(ref)

    if args.full:
        source_files = sorted(
            SOURCE.glob("*.json.gz"),
            key=lambda path: int(path.name.split(".", 1)[0]),
        )
        if len(source_files) != 114:
            raise SystemExit(f"expected 114 source chapters, found {len(source_files)}")
        jobs: list[tuple[int, set[str] | None]] = [
            (int(path.name.split(".", 1)[0]), None) for path in source_files
        ]
    else:
        jobs = sorted(refs_by_chapter.items())

    OUTPUT.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    for chapter, refs in jobs:
        target = OUTPUT / f"{chapter}.json.br"
        document = None
        if args.resume and target.exists():
            candidate = json.loads(brotli.decompress(target.read_bytes()))
            if "fixture_refs" not in candidate.get("_meta", {}):
                audit_v13_document(candidate)
                document = candidate
                print(f"chapter {chapter:03d}: reused audited output", flush=True)
        if document is None:
            document = _restamp(chapter, refs)
            encoded = json.dumps(
                document,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            target.write_bytes(brotli.compress(encoded))
        generated.append(target)
        counts = audit_v13_document(document)
        print(f"chapter {chapter:03d}: {counts}", flush=True)

    if args.full and len(generated) != 114:
        raise RuntimeError(f"expected 114 generated chapters, got {len(generated)}")
    if args.install:
        for target in generated:
            shutil.copy2(target, SOURCE / target.name)
        print(f"installed {len(generated)} audited v13 shards in {SOURCE}", flush=True)


if __name__ == "__main__":
    main()
