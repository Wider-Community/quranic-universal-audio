"""Server-side copy within or between buckets (Xet-dedup; no re-upload).

  bucket_cp.py reciters/<a>/detailed.json reciters/<b>/detailed.json
  bucket_cp.py reciters/<slug> reciters/<slug>-backup --bucket prod --yes-prod
  bucket_cp.py --src-bucket dev --dst-bucket prod reciters/<slug> reciters/<slug>  --yes-prod

Only works for files Xet already tracks; large MP3s qualify, freshly-written
small JSONs may need a brief wait before they're dedupable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _bootstrap as bs  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("src", help="source bucket path")
    p.add_argument("dst", help="destination bucket path")
    p.add_argument(
        "--src-bucket",
        choices=list(bs.BUCKETS),
        default=None,
        help="source bucket (default: --bucket)",
    )
    p.add_argument(
        "--dst-bucket",
        choices=list(bs.BUCKETS),
        default=None,
        help="destination bucket (default: --bucket)",
    )
    bs.add_bucket_args(p)
    a = p.parse_args()

    # `bucket` is the default if either side is unspecified; mutation gate
    # checks the *destination* — that's where bytes land.
    src_b = a.src_bucket or a.bucket
    dst_b = a.dst_bucket or a.bucket
    a.bucket = dst_b  # so confirm_mutation reads the right side
    bs.confirm_mutation(a, f"copy → {dst_b}:{a.dst}")

    bs.resolve(a)  # token load + utf-8 stdout; we use the lower-level API below
    from huggingface_hub import copy_files

    src = f"hf://buckets/{bs.BUCKETS[src_b]}/{a.src.rstrip('/')}"
    dst = f"hf://buckets/{bs.BUCKETS[dst_b]}/{a.dst.rstrip('/')}"
    copy_files(src, dst)
    print(f"copied {src_b}:{a.src} → {dst_b}:{a.dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
