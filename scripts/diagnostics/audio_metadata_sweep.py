"""Sweep catalog audio manifests for missing / wrong metadata.

Two defect classes, by_surah reciters only (by_ayah out of scope — skipped by
filename + key shape):

  A. NULL metadata   — chapter entries missing duration_sec / bitrate_kbps /
                       bitrate_mode (ayman_swed_muallim_tvquran is the canonical
                       case: all 114 chapters null except url+size).
  B. DURATION DRIFT  — manifest duration_sec disagrees with the peaks-header
                       duration_ms by more than --drift-pct. Peaks are derived
                       from DECODED audio, so a large positive drift (manifest
                       longer than peaks) is the phantom-tail signature
                       (maher_al_muaiqly_mp3quran ch76: 449s manifest vs ~300s real).

Pass A reads one file per reciter (cheap). Pass B additionally reads each
chapter's slim peaks header (heavier) — gate it with --peaks.

  python3 scripts/diagnostics/audio_metadata_sweep.py --bucket prod
  python3 scripts/diagnostics/audio_metadata_sweep.py --bucket prod --peaks --drift-pct 8
  python3 scripts/diagnostics/audio_metadata_sweep.py --bucket prod --peaks --json > /tmp/sweep.json
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bucket"))
import _bootstrap as bs  # noqa: E402

CHAPTER_FIELDS = ("duration_sec", "bitrate_kbps", "bitrate_mode")

# HF buckets API allows 2500 requests / 5 min (~8.3/s). Stay safely under with a
# process-wide token gate; every bucket call goes through _gate() first.
_RATE_HZ = 7.0
_gate_lock = threading.Lock()
_gate_next = [0.0]


def _gate() -> None:
    with _gate_lock:
        now = time.monotonic()
        wait = _gate_next[0] - now
        if wait > 0:
            time.sleep(wait)
            now = time.monotonic()
        _gate_next[0] = now + 1.0 / _RATE_HZ


def _retry(fn, *, tries: int = 4):
    """Call fn(); on 429 honor Retry-After (capped) and retry."""
    for attempt in range(tries):
        _gate()
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "429" in msg or "Too Many Requests" in msg:
                if attempt == tries - 1:
                    raise
                time.sleep(min(20.0, 2.0 * (attempt + 1)))
                continue
            raise


def is_by_ayah_name(slug: str) -> bool:
    return "everyayah" in slug or "byayah" in slug


def by_surah_chapter_keys(chapters: dict) -> list[str]:
    """Integer-keyed chapters only; skip '<s>:<a>' by_ayah keys defensively."""
    return [k for k in chapters if ":" not in k and k.isdigit()]


def scan_manifest(raw: bytes, slug: str) -> dict:
    """Pass A: structural null-metadata scan. Pure, no extra reads."""
    doc = json.loads(raw)
    chapters = doc.get("chapters") or {}
    keys = by_surah_chapter_keys(chapters)
    null_by_field = {f: [] for f in CHAPTER_FIELDS}
    for k in keys:
        entry = chapters[k] or {}
        for f in CHAPTER_FIELDS:
            v = entry.get(f)
            if v is None:
                null_by_field[f].append(k)
    return {
        "slug": slug,
        "n_chapters": len(keys),
        "null_by_field": {f: v for f, v in null_by_field.items() if v},
        "all_null": all(len(null_by_field[f]) == len(keys) for f in CHAPTER_FIELDS)
        and len(keys) > 0,
        "_chapters": {k: chapters[k] for k in keys},  # carried for pass B
    }


def peaks_duration_ms(fs, bucket: str, slug: str, chapter: str) -> int | None:
    """Read just duration_ms from the slim peaks gz header. None if absent."""
    path = bs.abs_path(bucket, f"reciters/{slug}/peaks/{chapter}.json.gz")
    try:
        blob = gzip.decompress(_retry(lambda: fs.cat_file(path)))
        env = json.loads(blob)
        d = env.get("duration_ms")
        return int(d) if isinstance(d, (int, float)) and d > 0 else None
    except FileNotFoundError:
        return None
    except Exception:
        return None


def peaks_chapters(fs, bucket: str, slug: str) -> set[str]:
    """One ls of the reciter's peaks dir → set of chapter keys that have peaks.

    Un-extracted reciters (catalog-only / CDN stream-through) have no peaks dir;
    returns empty set so drift_check skips them without 114 FileNotFound probes."""
    try:
        names = _retry(lambda: fs.ls(bs.abs_path(bucket, f"reciters/{slug}/peaks"), detail=False))
    except Exception:
        return set()
    return {n.rsplit("/", 1)[-1][: -len(".json.gz")] for n in names if n.endswith(".json.gz")}


def drift_check(fs, bucket: str, rec: dict, drift_pct: float) -> list[dict]:
    """Pass B: compare manifest duration_sec vs peaks duration_ms per chapter."""
    have = peaks_chapters(fs, bucket, rec["slug"])
    if not have:
        return []
    out = []
    for k, entry in rec["_chapters"].items():
        if k not in have:
            continue
        man_sec = (entry or {}).get("duration_sec")
        if not isinstance(man_sec, (int, float)) or man_sec <= 0:
            continue  # nulls already flagged in pass A
        pk_ms = peaks_duration_ms(fs, bucket, rec["slug"], k)
        if pk_ms is None:
            continue  # no peaks to compare against
        pk_sec = pk_ms / 1000.0
        diff = man_sec - pk_sec
        pct = abs(diff) / pk_sec * 100.0 if pk_sec else 0.0
        if pct >= drift_pct:
            out.append(
                {
                    "chapter": k,
                    "manifest_sec": round(float(man_sec), 1),
                    "peaks_sec": round(pk_sec, 1),
                    "drift_sec": round(diff, 1),
                    "drift_pct": round(pct, 1),
                    "phantom_tail": diff > 0,  # manifest longer than real audio
                }
            )
    return out


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--peaks", action="store_true", help="run pass B (duration drift vs peaks)")
    p.add_argument("--drift-pct", type=float, default=8.0, help="drift threshold %% (default 8)")
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--json", action="store_true", help="emit JSON report to stdout")
    p.add_argument("--slug", default="", help="filter: substring match on slug")
    bs.add_bucket_args(p)
    a = p.parse_args()

    fs, bucket = bs.resolve(a)
    man_dir = bs.abs_path(bucket, "catalog/audio_manifest")

    print(f"listing {man_dir} ...", file=sys.stderr)
    paths = [pth for pth in fs.ls(man_dir, detail=False) if pth.endswith(".json")]

    def slug_of(pth: str) -> str:
        return pth.rsplit("/", 1)[-1][: -len(".json")]

    targets = [
        pth
        for pth in paths
        if not is_by_ayah_name(slug_of(pth)) and (not a.slug or a.slug in slug_of(pth))
    ]
    n_skipped = len(paths) - len([p for p in paths if not is_by_ayah_name(slug_of(p))])
    print(
        f"{len(paths)} manifests; {n_skipped} by_ayah skipped; scanning {len(targets)} by_surah",
        file=sys.stderr,
    )

    # Pass A — parallel read + structural scan.
    def fetch_scan(pth: str) -> dict | None:
        slug = slug_of(pth)
        try:
            raw = _retry(lambda: fs.cat_file(pth))
            return scan_manifest(raw, slug)
        except Exception as e:  # noqa: BLE001
            return {"slug": slug, "error": repr(e)}

    recs: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for i, r in enumerate(ex.map(fetch_scan, targets), 1):
            if r:
                recs.append(r)
            if i % 50 == 0:
                print(f"  pass A {i}/{len(targets)}", file=sys.stderr)

    null_recs = [r for r in recs if r.get("null_by_field")]
    err_recs = [r for r in recs if r.get("error")]

    # Pass B — duration drift (optional, heavier).
    drift_recs: list[dict] = []
    if a.peaks:
        scannable = [r for r in recs if not r.get("error") and r.get("_chapters")]
        print(f"pass B: drift-checking {len(scannable)} reciters ...", file=sys.stderr)
        with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
            futs = {ex.submit(drift_check, fs, bucket, r, a.drift_pct): r for r in scannable}
            for i, fut in enumerate(cf.as_completed(futs), 1):
                r = futs[fut]
                hits = fut.result()
                if hits:
                    drift_recs.append({"slug": r["slug"], "chapters": hits})
                if i % 50 == 0:
                    print(f"  pass B {i}/{len(scannable)}", file=sys.stderr)

    for r in recs:
        r.pop("_chapters", None)

    report = {
        "bucket": bucket,
        "n_by_surah": len(targets),
        "null_metadata": null_recs,
        "duration_drift": drift_recs,
        "errors": err_recs,
    }

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    # Human report.
    print(f"\n==== NULL METADATA ({len(null_recs)} reciters) ====")
    for r in sorted(null_recs, key=lambda r: r["slug"]):
        flag = " [ALL-NULL]" if r.get("all_null") else ""
        parts = []
        for f, ks in r["null_by_field"].items():
            parts.append(f"{f}={len(ks)}/{r['n_chapters']}")
        print(f"  {r['slug']}{flag}: " + ", ".join(parts))

    if a.peaks:
        print(f"\n==== DURATION DRIFT >= {a.drift_pct}% ({len(drift_recs)} reciters) ====")
        for r in sorted(drift_recs, key=lambda r: r["slug"]):
            print(f"  {r['slug']}:")
            for h in sorted(r["chapters"], key=lambda h: -h["drift_pct"]):
                tail = " PHANTOM-TAIL" if h["phantom_tail"] else ""
                print(
                    f"    ch{h['chapter']}: manifest={h['manifest_sec']}s "
                    f"peaks={h['peaks_sec']}s drift={h['drift_sec']:+}s "
                    f"({h['drift_pct']}%){tail}"
                )

    if err_recs:
        print(f"\n==== ERRORS ({len(err_recs)}) ====")
        for r in err_recs:
            print(f"  {r['slug']}: {r['error']}")

    print(
        f"\nsummary: {len(null_recs)} null, "
        f"{len(drift_recs)} drift, {len(err_recs)} errors / {len(targets)} by_surah",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
