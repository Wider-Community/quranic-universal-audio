"""List files/dirs at a bucket path.

  bucket_ls.py reciters                          # top-level dirs under reciters/
  bucket_ls.py reciters/husary --detail          # with sizes
  bucket_ls.py reciters --bucket prod --recursive
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _bootstrap as bs  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("path", nargs="?", default="",
                   help="path within the bucket (default: root)")
    p.add_argument("--detail", action="store_true",
                   help="show size + type per entry")
    p.add_argument("--recursive", action="store_true",
                   help="walk into subdirectories")
    bs.add_bucket_args(p)
    a = p.parse_args()

    fs, bucket = bs.resolve(a)
    target = bs.abs_path(bucket, a.path)

    if a.recursive:
        # find() returns flat paths; cheaper than ls with detail when scanning trees
        items = fs.find(target, detail=a.detail) if a.detail else fs.find(target)
    else:
        items = fs.ls(target, detail=a.detail)

    if a.detail:
        rows = items.values() if isinstance(items, dict) else items
        for row in rows:
            name = row["name"].split("/", 3)[-1] if "name" in row else str(row)
            t = row.get("type", "?")
            sz = bs.fmt_size(row.get("size")) if t == "file" else "—"
            print(f"{t:5s} {sz:>10s}  {name}")
    else:
        for entry in items:
            # entries come as "buckets/<owner>/<bucket>/<path>" — strip prefix
            print(entry.split("/", 3)[-1])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
