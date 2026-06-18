"""Backfill per-letter silent flags + silence marks into existing timestamp shards.

Stamps the schema-v4 silent data onto every segment-array shard already on the
bucket — a 4th ``silent`` bool on each letter and the silence combining mark
(``۟`` / ``۠``) folded onto its char — using the same
``qua_shared.timestamps_bridges._stamp_silent_flags`` the live pipeline runs.
**Letters only**: phones / cross-word bridge tags are left untouched, so this is a
minimal, additive change to shards that were already bridge-tagged. No MFA / audio
— each gap-bounded run is re-phonemized to derive its silent flags (any timing gap
is a stop, so a silah drops at waqf), exactly like a regen but without re-aligning.

Idempotent: re-running no-ops on an already-stamped shard (the char-match guard
sees the folded mark and skips). After a silent-logic change (e.g. the carrier-waw
silence in 2.6) pass ``--restamp`` to reset already-stamped letters to bare and
re-derive — no re-alignment, since the flags are a pure function of the text.
Requires ``quranic-phonemizer>=2.7``.

Dry-run by default: reports per-reciter coverage (letters / stamped / silent /
marked / NO-SLOT) WITHOUT writing. ``--write`` uploads the stamped shards via
batched Xet (parallel); ``--bucket prod`` additionally needs ``--yes-prod``.
``--backup-dir`` saves each original shard locally before it is overwritten.

    # report only, prod
    python scripts/backfills/backfill_silent_flags.py --all --bucket prod
    # migrate prod with a local backup
    python scripts/backfills/backfill_silent_flags.py --all --bucket prod --yes-prod \\
        --write --backup-dir .local/backups/silent_v4
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bucket"))
import _bootstrap as bs  # noqa: E402

from qua_shared.timestamps_bridges import _stamp_silent_flags  # noqa: E402
from qua_shared.timestamps_shards import (  # noqa: E402
    SEGMENT_SCHEMA_VERSION,
    gzip_shard,
)

_SILENT_MARKS = {"۟", "۠"}  # ۟ SILENT_ALWAYS, ۠ SILENT_AT_CONTINUATION


def _rl(fn, *args, **kwargs):
    """Run a bucket op, backing off on HF 429 rate-limit errors."""
    for attempt in range(8):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "429" not in msg and "rate limit" not in msg.lower():
                raise
            m = re.search(r"[Rr]etry after (\d+)", msg)
            wait = (int(m.group(1)) + 5) if m else 60
            print(f"  rate-limited — sleeping {wait}s (attempt {attempt + 1}/8)", flush=True)
            time.sleep(wait)
    raise RuntimeError("rate-limit retries exhausted")


def _list_reciters(fs, bucket: str) -> list[str]:
    base = bs.abs_path(bucket, "reciters")
    return sorted(p.split("/")[-1] for p in _rl(fs.ls, base, detail=False))


def _shard_paths(fs, bucket: str, slug: str) -> list[tuple[int, str]]:
    base = bs.abs_path(bucket, f"reciters/{slug}/timestamps")
    try:
        files = _rl(fs.ls, base, detail=False)
    except FileNotFoundError:
        return []
    out = [
        (int(f.split("/")[-1].split(".")[0]), f)
        for f in files
        if f.split("/")[-1].endswith(".json.gz")
    ]
    return sorted(out)


def _unstamp_words(words) -> None:
    """Reset every letter to its aligner-bare ``[char, start, end]`` — strip any
    folded silence mark and drop the 4th ``silent`` slot — so a re-stamp re-derives
    the flags from scratch. Without this the char-guard sees the folded mark, the
    bare phonemizer char mismatches, and the run is skipped (so a silent-logic
    change like 2.6 carrier-waw never reaches an already-stamped shard)."""
    for word in words:
        for lt in word[3]:
            lt[0] = "".join(c for c in lt[0] if c not in _SILENT_MARKS)
            del lt[3:]


def _stamp_shard(pm, data: dict, *, restamp: bool = False) -> Counter:
    """Stamp every segment's letters in place. Returns a coverage Counter.

    ``restamp`` first resets already-stamped letters to bare so the silent flags
    are re-derived (use after a silent-logic change); otherwise stamping no-ops on
    a folded shard."""
    cov = Counter()
    for seg in data.get("segments", []):
        if restamp:
            _unstamp_words(seg["words"])
        _stamp_silent_flags(pm, seg["ref"], seg["words"])
    for seg in data.get("segments", []):
        for word in seg["words"]:
            for lt in word[3]:
                cov["letters"] += 1
                if len(lt) >= 4:
                    cov["stamped"] += 1
                    if lt[3]:
                        cov["silent"] += 1
                else:
                    cov["noslot"] += 1
                if any(c in _SILENT_MARKS for c in lt[0]):
                    cov["marked"] += 1
    return cov


def process_reciter(
    fs, pm, bucket: str, slug: str, *, write: bool, backup_dir: str | None, restamp: bool = False
) -> tuple[Counter, str]:
    shards = _shard_paths(fs, bucket, slug)
    if not shards:
        return Counter(), ""
    cov = Counter()
    adds: list[tuple[str, str]] = []
    tmpdir = tempfile.mkdtemp(prefix="silentbf_") if write else None
    for ch, path in shards:
        raw = _rl(fs.read_bytes, path)
        if backup_dir:
            dst = Path(backup_dir) / slug / f"{ch}.json.gz"
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(raw)
        data = json.loads(gzip.decompress(raw))
        cov += _stamp_shard(pm, data, restamp=restamp)
        cov["shards"] += 1
        if write:
            data.setdefault("_meta", {})["schema_version"] = SEGMENT_SCHEMA_VERSION
            local = os.path.join(tmpdir, f"{ch}.json.gz")
            Path(local).write_bytes(gzip_shard(data))
            adds.append((local, f"reciters/{slug}/timestamps/{ch}.json.gz"))
    if write and adds:
        from huggingface_hub import batch_bucket_files

        _rl(batch_bucket_files, bucket, add=adds)  # batched parallel Xet upload
    line = (
        f"{slug:44} shards={cov['shards']:3} letters={cov['letters']:6} "
        f"stamped={cov['stamped']:6} silent={cov['silent']:6} marked={cov['marked']:5} "
        f"NO-SLOT={cov['noslot']:4}" + ("  [WROTE]" if write else "")
    )
    return cov, line


def _mp_worker(task: tuple) -> tuple[dict, str]:
    """ProcessPool entrypoint — builds its own fs + phonemizer per process."""
    slug, bucket, write, backup_dir, restamp = task
    from huggingface_hub import HfFileSystem
    from quranic_phonemizer import Phonemizer

    fs = HfFileSystem(token=os.environ.get("HF_TOKEN"))
    cov, line = process_reciter(
        fs, Phonemizer(), bucket, slug, write=write, backup_dir=backup_dir, restamp=restamp
    )
    return dict(cov), line


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--slug", help="single reciter slug")
    g.add_argument("--all", action="store_true", help="every reciter with timestamps")
    ap.add_argument("--write", action="store_true", help="upload stamped shards (default: dry-run)")
    ap.add_argument("--backup-dir", help="save each original shard here before overwriting")
    ap.add_argument("--workers", type=int, default=1, help="parallel reciter processes")
    ap.add_argument(
        "--restamp",
        action="store_true",
        help="reset already-stamped letters to bare and re-derive (after a silent-logic change)",
    )
    bs.add_bucket_args(ap)
    args = ap.parse_args()
    if args.write:
        bs.confirm_mutation(args, "backfill silent flags")

    fs, bucket = bs.resolve(args)
    slugs = [args.slug] if args.slug else _list_reciters(fs, bucket)

    def log(msg):
        print(msg, flush=True)

    t0 = time.time()
    grand = Counter()
    if args.workers > 1:
        from concurrent.futures import ProcessPoolExecutor

        tasks = [(s, bucket, args.write, args.backup_dir, args.restamp) for s in slugs]
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for cov, line in ex.map(_mp_worker, tasks):
                if line:
                    log(line)
                grand += Counter(cov)
    else:
        from quranic_phonemizer import Phonemizer

        pm = Phonemizer()
        for slug in slugs:
            cov, line = process_reciter(
                fs,
                pm,
                bucket,
                slug,
                write=args.write,
                backup_dir=args.backup_dir,
                restamp=args.restamp,
            )
            if line:
                log(line)
            grand += cov
    dt = time.time() - t0
    noslot = grand["noslot"]
    pct = (100 * noslot / grand["letters"]) if grand["letters"] else 0
    log(
        f"\n=== TOTAL: {grand['shards']} shards, {grand['letters']} letters, "
        f"{grand['stamped']} stamped ({grand['silent']} silent, {grand['marked']} marked), "
        f"NO-SLOT={noslot} ({pct:.1f}%) in {dt:.0f}s "
        f"({'DRY-RUN' if not args.write else 'WROTE v=' + str(SEGMENT_SCHEMA_VERSION)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
