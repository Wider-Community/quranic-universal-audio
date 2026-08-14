"""Backfill per-character cells into existing timestamp shards.

Stamps the 6th word slot ``cells[]`` onto every segment-array shard, using the
same ``qua_sdk.components.timing.lib.cells.annotate_segment_words`` the live
pipeline runs — so a backfilled shard is byte-identical to a fresh generation.
Re-phonemizing each segment also re-applies silent flags + bridge tags (both
idempotent), bringing an older shard up to ``SEGMENT_SCHEMA_VERSION`` in one pass,
then bumps ``_meta.schema_version`` to it. Cells include ``role == "base"`` (the
producer emits the full per-character breakdown) and carry an ordered ``rules``
list, so a shard written before the seven-slot row needs ``--restamp``.

Cell ``phoneme_indices`` are word-local indices over the word's *indexable*
phones (the render-only qalqala ``Q`` excluded — same coordinate space as the
bridge index), so they line up with the stored phones regardless of which
render-only markers a model emits.

Dry-run by default: reports per-reciter cell counts, the status/tag distribution,
and any anti-drift violation (a cell index past the word's indexable phones)
WITHOUT writing. ``--write`` uploads (``--bucket prod`` also
needs ``--yes-prod``). ``--restamp`` re-derives cells on already-current shards.
``--local-dir DIR`` processes local ``*.shard.json`` / ``*.json.gz`` files
instead of the bucket (no HF token needed) — used to regenerate inspector
fixtures.

    # report only, prod bucket
    python scripts/backfills/backfill_cells.py --all --bucket prod
    # write one reciter
    python scripts/backfills/backfill_cells.py --slug nasser_al_qatami_mp3quran \\
        --bucket prod --yes-prod --write
    # regenerate local fixtures
    python scripts/backfills/backfill_cells.py --local-dir some/dir --write
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bucket"))
import _bootstrap as bs  # noqa: E402
from qua_sdk.components.timing.lib.cells import (  # noqa: E402
    _is_indexable,
    annotate_ordered_segments,
)

from qua_shared import ts_shard_cells  # noqa: E402
from qua_shared.timestamps_shards import SEGMENT_SCHEMA_VERSION, gzip_shard  # noqa: E402


def _rl(fn, *args, **kwargs):
    """Run a bucket op, backing off on HF 429 rate-limit errors."""
    for attempt in range(8):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            msg = str(e)
            if "429" not in msg and "rate limit" not in msg.lower():
                raise
            m = re.search(r"[Rr]etry after (\d+)", msg)
            wait = (int(m.group(1)) + 5) if m else 60
            print(f"  rate-limited — sleeping {wait}s (attempt {attempt + 1}/8)", flush=True)
            time.sleep(wait)
    raise RuntimeError("rate-limit retries exhausted")


def _stamp_doc(data: dict, *, restamp: bool) -> tuple[int, Counter, Counter, list]:
    """Stamp cells across every segment of a shard doc, in place.

    Returns ``(n_cells, status_dist, tag_dist, violations)``, where ``tag_dist``
    counts every rule on every cell (a cell carries an ordered list, not one tag).
    A violation is a cell index past the word's indexable phones, which means
    phonemizer/shard drift and is never written silently."""
    if restamp:
        for seg in data.get("segments", []):
            for wd in seg["words"]:
                if len(wd) > 5:
                    del wd[5:]
    # Stamp in recitation order with the waṣl context threaded (the shard segments
    # are already time-ordered + carry the per-segment `wasl` boundary flag), so a
    # waṣl-continued boundary's cells derive in continuation form and don't drop —
    # the same linking generation does via annotate_v2_doc.
    seq = [(seg["ref"], seg["words"], bool(seg.get("wasl"))) for seg in data.get("segments", [])]
    annotate_ordered_segments(seq)

    n_cells = 0
    status_dist: Counter = Counter()
    tag_dist: Counter = Counter()
    violations: list = []
    for seg in data.get("segments", []):
        for wd in seg["words"]:
            n_idx = sum(1 for ph in wd[4] if _is_indexable(ph[0]))
            for c in ts_shard_cells.word_cells(wd):
                n_cells += 1
                status_dist[c.status] += 1
                tag_dist.update(c.rules)
                for i in c.phoneme_indices:
                    if not (0 <= i < n_idx):
                        violations.append((seg["ref"], wd[0], "idx-oob", i, n_idx))
    return n_cells, status_dist, tag_dist, violations


# --- bucket mode -----------------------------------------------------------


def _list_reciters(fs, bucket: str) -> list[str]:
    base = bs.abs_path(bucket, "reciters")
    return sorted(p.split("/")[-1] for p in _rl(fs.ls, base, detail=False))


def _shard_paths(fs, bucket: str, slug: str) -> list[tuple[int, str]]:
    base = bs.abs_path(bucket, f"reciters/{slug}/timestamps")
    try:
        files = _rl(fs.ls, base, detail=False)
    except FileNotFoundError:
        return []
    out = []
    for f in files:
        name = f.split("/")[-1]
        if name.endswith(".json.gz"):
            out.append((int(name.split(".")[0]), f))
    return sorted(out)


def process_reciter(fs, bucket: str, slug: str, *, write: bool, restamp: bool, log) -> dict:
    shards = _shard_paths(fs, bucket, slug)
    if not shards:
        return {}
    status = Counter()
    tags = Counter()
    total_cells = skipped = 0
    violations: list = []
    to_write: dict[str, bytes] = {}
    for _ch, path in shards:
        data = json.loads(gzip.decompress(_rl(fs.read_bytes, path)))
        if data.get("_meta", {}).get("schema_version", 0) >= SEGMENT_SCHEMA_VERSION and not restamp:
            skipped += 1
            continue
        n, sd, td, viol = _stamp_doc(data, restamp=restamp)
        total_cells += n
        status.update(sd)
        tags.update(td)
        violations += viol
        if write and not viol:
            data.setdefault("_meta", {})["schema_version"] = SEGMENT_SCHEMA_VERSION
            to_write[f"reciters/{slug}/timestamps/{_ch}.json.gz"] = gzip_shard(data)
    # One Xet batch per reciter (paths, not bytes) — far faster than a commit/file.
    if to_write:
        bs.batch_write(bucket, to_write)
    written_chapters = sorted(int(p.rsplit("/", 1)[-1].split(".")[0]) for p in to_write)
    log(
        f"{slug:44} shards={len(shards):3} cells={total_cells:6} skipped={skipped:3} "
        f"violations={len(violations)}"
        + ("" if not violations else f"  !! {violations[:3]}")
        + ("  [WROTE]" if write and not violations else "")
    )
    return {
        "status": status,
        "tags": tags,
        "violations": violations,
        "written_chapters": written_chapters,
    }


# --- local-dir mode --------------------------------------------------------


def _load_local(path: Path) -> dict:
    raw = path.read_bytes()
    if path.suffix == ".gz":
        raw = gzip.decompress(raw)
    return json.loads(raw)


def _write_local(path: Path, data: dict) -> None:
    if path.suffix == ".gz":
        path.write_bytes(gzip_shard(data))
    else:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def process_local_dir(d: Path, *, write: bool, restamp: bool, log, quiet: bool = False) -> dict:
    files = sorted(
        p for p in d.iterdir() if p.name.endswith(".shard.json") or p.name.endswith(".json.gz")
    )
    status = Counter()
    tags = Counter()
    total_cells = 0
    violations: list = []
    for path in files:
        data = _load_local(path)
        if data.get("_meta", {}).get("schema_version", 0) >= SEGMENT_SCHEMA_VERSION and not restamp:
            if not quiet:
                log(f"  {path.name}: already v{SEGMENT_SCHEMA_VERSION}, skip")
            continue
        n, sd, td, viol = _stamp_doc(data, restamp=restamp)
        total_cells += n
        status.update(sd)
        tags.update(td)
        violations += viol
        if write and not viol:
            data.setdefault("_meta", {})["schema_version"] = SEGMENT_SCHEMA_VERSION
            _write_local(path, data)
        if not quiet:
            log(
                f"  {path.name}: cells={n} violations={len(viol)}"
                + ("  [WROTE]" if write and not viol else "")
            )
    return {"status": status, "tags": tags, "violations": violations, "cells": total_cells}


def process_local_root(root: Path, *, write: bool, restamp: bool, log) -> dict:
    """Process every ``reciters/<slug>/timestamps`` shard dir under ``root``."""
    status = Counter()
    tags = Counter()
    violations: list = []
    rec_base = root / "reciters"
    slugs = (
        sorted(p.name for p in rec_base.iterdir() if (p / "timestamps").is_dir())
        if rec_base.is_dir()
        else []
    )
    for slug in slugs:
        res = process_local_dir(
            rec_base / slug / "timestamps", write=write, restamp=restamp, log=log, quiet=True
        )
        status.update(res["status"])
        tags.update(res["tags"])
        violations += res["violations"]
        log(
            f"  {slug:44} cells={res['cells']:6} violations={len(res['violations'])}"
            + ("  [WROTE]" if write and not res["violations"] else "")
        )
    return {"status": status, "tags": tags, "violations": violations}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--slug", help="single reciter slug")
    g.add_argument("--all", action="store_true", help="every reciter with timestamps")
    g.add_argument("--local-dir", help="process local shard files in DIR (no bucket)")
    g.add_argument("--local-root", help="process every reciters/*/timestamps under DIR (no bucket)")
    ap.add_argument("--write", action="store_true", help="write stamped shards (default: dry-run)")
    ap.add_argument(
        "--restamp", action="store_true", help="re-derive cells even on current-version shards"
    )
    bs.add_bucket_args(ap)
    bs.add_notify_args(ap)
    args = ap.parse_args()

    def log(msg):
        print(msg, flush=True)

    grand_status = Counter()
    grand_tags = Counter()
    grand_viol = 0

    if args.local_dir or args.local_root:
        if args.local_root:
            res = process_local_root(
                Path(args.local_root), write=args.write, restamp=args.restamp, log=log
            )
        else:
            res = process_local_dir(
                Path(args.local_dir), write=args.write, restamp=args.restamp, log=log
            )
        grand_status.update(res["status"])
        grand_tags.update(res["tags"])
        grand_viol += len(res["violations"])
    else:
        if args.write:
            bs.confirm_mutation(args, "backfill cells")
        fs, bucket = bs.resolve(args)
        slugs = [args.slug] if args.slug else _list_reciters(fs, bucket)
        for slug in slugs:
            res = process_reciter(fs, bucket, slug, write=args.write, restamp=args.restamp, log=log)
            if res:
                grand_status.update(res["status"])
                grand_tags.update(res["tags"])
                grand_viol += len(res["violations"])
                # Tell the Inspector the shards changed so staleness re-evaluates
                # (otherwise this bucket-direct write is silent). Best-effort.
                if args.write and res["written_chapters"]:
                    bs.notify_ts_refreshed(
                        args, slug, chapters=res["written_chapters"], reason="backfill_cells"
                    )

    log("\n=== corpus cell status distribution ===")
    for st, c in grand_status.most_common():
        log(f"  {c:7}  {st}")
    log("=== corpus cell tag distribution ===")
    for tg, c in grand_tags.most_common():
        log(f"  {c:7}  {tg}")
    log(
        f"\ntotal violations: {grand_viol}  "
        f"({'DRY-RUN' if not args.write else 'WROTE schema_version=' + str(SEGMENT_SCHEMA_VERSION)})"
    )
    return 1 if grand_viol else 0


if __name__ == "__main__":
    raise SystemExit(main())
