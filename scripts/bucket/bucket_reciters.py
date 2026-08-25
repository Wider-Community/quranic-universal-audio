"""One-line-per-reciter summary against a bucket: file count, total audio MB,
max chapter MB, peaks coverage, whether _done.json is present.

  bucket_reciters.py                              # dev bucket, table
  bucket_reciters.py --bucket prod --sort size    # sort by total bytes
  bucket_reciters.py --bucket prod --slug husary  # filter (substring match)
  bucket_reciters.py --bucket prod --json         # for piping into other tools

Doesn't read the DB — pure bucket listing — so it works without pulling the
SQLite. For state+marked_ready columns combine with the inspector-admin
``admin_reciter.py`` script.
"""

from __future__ import annotations

import argparse
import json as _json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).parent))
import _bootstrap as bs  # noqa: E402


def _summary(fs, bucket: str, slug: str) -> dict:
    base = bs.abs_path(bucket, f"reciters/{slug}")
    info = fs.find(base, detail=True)
    files = [(k, v) for k, v in info.items() if v.get("type") == "file"]
    audio = [v.get("size", 0) for k, v in files if "/audio/" in k and k.endswith(".mp3")]
    peaks = [k for k, _ in files if "/peaks/" in k and k.endswith(".json.gz")]
    ts_shards = [
        k
        for k, _ in files
        if "/timestamps/" in k and (k.endswith(".json") or k.endswith(".json.br"))
    ]
    return {
        "slug": slug,
        "n_files": len(files),
        "total_b": sum(v.get("size", 0) for _, v in files),
        "audio_n": len(audio),
        "audio_total_b": sum(audio),
        "audio_max_b": max(audio) if audio else 0,
        "peaks_n": len(peaks),
        "ts_shards": len(ts_shards),
        "done": any(k.endswith("audio/_done.json") for k, _ in files),
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--slug", help="filter slugs by substring")
    p.add_argument("--sort", choices=("slug", "size", "audio", "max"), default="slug")
    p.add_argument("--json", action="store_true", help="emit JSON instead of table")
    p.add_argument("--workers", type=int, default=8, help="parallel fan-out for per-slug listing")
    bs.add_bucket_args(p)
    a = p.parse_args()

    fs, bucket = bs.resolve(a)

    dirs = cast(list[str], fs.ls(bs.abs_path(bucket, "reciters"), detail=False))
    slugs = sorted(d.rsplit("/", 1)[-1] for d in dirs)
    if a.slug:
        slugs = [s for s in slugs if a.slug.lower() in s.lower()]
    if not slugs:
        print("(no reciters)")
        return 0

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        rows = list(ex.map(lambda s: _summary(fs, bucket, s), slugs))

    key = {
        "slug": lambda r: r["slug"],
        "size": lambda r: -r["total_b"],
        "audio": lambda r: -r["audio_total_b"],
        "max": lambda r: -r["audio_max_b"],
    }[a.sort]
    rows.sort(key=key)

    if a.json:
        print(_json.dumps(rows, indent=2))
        return 0

    print(
        f"{'slug':<55s} {'files':>6s} {'total':>10s} "
        f"{'audio':>10s} {'maxCh':>9s} {'pk':>3s} {'ts':>3s} {'done':>5s}"
    )
    print("-" * 110)
    for r in rows:
        print(
            f"{r['slug']:<55s} {r['n_files']:>6d} "
            f"{bs.fmt_size(r['total_b']):>10s} "
            f"{bs.fmt_size(r['audio_total_b']):>10s} "
            f"{bs.fmt_size(r['audio_max_b']):>9s} "
            f"{r['peaks_n']:>3d} {r['ts_shards']:>3d} "
            f"{'yes' if r['done'] else 'no':>5s}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
