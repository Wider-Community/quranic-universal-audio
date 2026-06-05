"""Backfill cross-word tajweed bridge tags into existing timestamp shards.

Stamps the per-phone bridge rule (slot 5 of each phone tuple) onto every
segment-array shard already on the bucket and bumps ``_meta.schema_version``
2 → 3, using the same ``qua_shared.timestamps_bridges`` logic the live pipeline
now runs. No MFA / audio — the merger phone is located by re-phonemizing each
segment's word range, which reproduces the stored phone sequence byte-for-byte
(verified across the published corpus).

Dry-run by default: reports per-reciter tag counts, the per-rule distribution,
and any anti-drift violation (a tag landing on a non-merger phone) WITHOUT
writing. Pass ``--write`` to upload the re-tagged shards (``--bucket prod``
additionally needs ``--yes-prod``).

    # report only, prod
    python scripts/backfills/backfill_bridge_tags.py --all --bucket prod
    # write one reciter
    python scripts/backfills/backfill_bridge_tags.py --slug mahmoud_khalil_al_husary_mp3quran \\
        --bucket prod --yes-prod --write
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bucket"))
import _bootstrap as bs  # noqa: E402

from qua_shared.timestamps_bridges import (  # noqa: E402
    _looks_like_merger,
    tag_segment_words,
)
from qua_shared.timestamps_shards import (  # noqa: E402
    SEGMENT_SCHEMA_VERSION,
    gzip_shard,
)


def _list_reciters(fs, bucket: str) -> list[str]:
    base = bs.abs_path(bucket, "reciters")
    return sorted(p.split("/")[-1] for p in fs.ls(base, detail=False))


def _shard_paths(fs, bucket: str, slug: str) -> list[tuple[int, str]]:
    base = bs.abs_path(bucket, f"reciters/{slug}/timestamps")
    try:
        files = fs.ls(base, detail=False)
    except FileNotFoundError:
        return []
    out = []
    for f in files:
        name = f.split("/")[-1]
        if name.endswith(".json.gz"):
            out.append((int(name.split(".")[0]), f))
    return sorted(out)


def _tag_shard(pm, data: dict) -> tuple[int, int, list]:
    """Tag every segment in a shard doc (in place). Returns
    ``(n_tagged, n_repeat_segments, violations)``."""
    tagged = 0
    repeats = 0
    violations = []
    for seg in data.get("segments", []):
        wns = [w[0] for w in seg["words"]]
        if wns != sorted(set(wns)):
            repeats += 1
            continue
        tagged += tag_segment_words(pm, seg["ref"], seg["words"])
    # Anti-drift: every stamped phone must look like a merger.
    for seg in data.get("segments", []):
        for word in seg["words"]:
            for ph in word[4]:
                if len(ph) > 5 and ph[5] and not _looks_like_merger(ph[0]):
                    violations.append((seg["ref"], ph[0], ph[5]))
    return tagged, repeats, violations


def process_reciter(fs, bucket: str, slug: str, *, write: bool, log) -> dict:
    shards = _shard_paths(fs, bucket, slug)
    if not shards:
        return {}
    from quranic_phonemizer import Phonemizer  # lazy

    pm = _PM[0] or Phonemizer()
    _PM[0] = pm

    dist = Counter()
    total_tagged = total_repeat = 0
    violations = []
    for _ch, path in shards:
        data = json.loads(gzip.decompress(fs.read_bytes(path)))
        n, rep, viol = _tag_shard(pm, data)
        total_tagged += n
        total_repeat += rep
        violations += viol
        for seg in data.get("segments", []):
            for word in seg["words"]:
                for phn in word[4]:
                    if len(phn) > 5 and phn[5]:
                        dist[phn[5]] += 1
        if write:
            data.setdefault("_meta", {})["schema_version"] = SEGMENT_SCHEMA_VERSION
            with fs.open(path, "wb") as fh:
                fh.write(gzip_shard(data))
    log(
        f"{slug:44} shards={len(shards):3} tagged={total_tagged:6} "
        f"repeat_segs={total_repeat:4} violations={len(violations)}"
        + ("" if not violations else f"  !! {violations[:3]}")
        + ("  [WROTE]" if write else "")
    )
    return {"dist": dist, "violations": violations, "tagged": total_tagged}


_PM = [None]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--slug", help="single reciter slug")
    g.add_argument("--all", action="store_true", help="every reciter with timestamps")
    ap.add_argument("--write", action="store_true", help="upload re-tagged shards (default: dry-run)")
    bs.add_bucket_args(ap)
    args = ap.parse_args()
    if args.write:
        bs.confirm_mutation(args, "backfill bridge tags")

    fs, bucket = bs.resolve(args)

    def log(msg):
        print(msg, flush=True)

    slugs = [args.slug] if args.slug else _list_reciters(fs, bucket)
    grand = Counter()
    grand_viol = 0
    for slug in slugs:
        res = process_reciter(fs, bucket, slug, write=args.write, log=log)
        if res:
            grand.update(res["dist"])
            grand_viol += len(res["violations"])

    log("\n=== corpus bridge distribution ===")
    for rule, c in grand.most_common():
        log(f"  {c:6}  {rule}")
    log(f"\ntotal violations: {grand_viol}  ({'DRY-RUN' if not args.write else 'WROTE schema_version=' + str(SEGMENT_SCHEMA_VERSION)})")
    return 1 if grand_viol else 0


if __name__ == "__main__":
    raise SystemExit(main())
