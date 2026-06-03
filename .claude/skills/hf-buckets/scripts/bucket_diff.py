"""Show what artifacts exist for a slug on one bucket but not the other.

  bucket_diff.py mahmoud_khalil_al_husary_mp3quran          # dev vs prod (default)
  bucket_diff.py <slug> --bucket-a dev --bucket-b aligner
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _bootstrap as bs  # noqa: E402


def _list(fs, bucket: str, slug: str) -> dict[str, int]:
    base = bs.abs_path(bucket, f"reciters/{slug}")
    try:
        info = fs.find(base, detail=True)
    except Exception:
        return {}
    out: dict[str, int] = {}
    for k, v in info.items():
        if v.get("type") != "file":
            continue
        # Strip "buckets/<owner>/<bucket>/reciters/<slug>/" prefix for diffing.
        rel = k.split(f"/reciters/{slug}/", 1)[-1]
        out[rel] = v.get("size", 0)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("slug")
    p.add_argument("--bucket-a", choices=list(bs.BUCKETS), default="dev")
    p.add_argument("--bucket-b", choices=list(bs.BUCKETS), default="prod")
    a = p.parse_args()

    bs.ensure_utf8_stdout()
    bs.load_hf_token()
    from huggingface_hub import HfFileSystem
    fs = HfFileSystem()

    A = _list(fs, bs.BUCKETS[a.bucket_a], a.slug)
    B = _list(fs, bs.BUCKETS[a.bucket_b], a.slug)
    only_a = sorted(set(A) - set(B))
    only_b = sorted(set(B) - set(A))
    diff_size = sorted(k for k in (set(A) & set(B)) if A[k] != B[k])

    print(f"diff {a.bucket_a} vs {a.bucket_b} for {a.slug}")
    print(f"  only on {a.bucket_a}: {len(only_a)}   "
          f"only on {a.bucket_b}: {len(only_b)}   size mismatch: {len(diff_size)}")
    for k in only_a:
        print(f"  - {a.bucket_a}: {k}  ({bs.fmt_size(A[k])})")
    for k in only_b:
        print(f"  + {a.bucket_b}: {k}  ({bs.fmt_size(B[k])})")
    for k in diff_size:
        print(f"  ~ {k}  {a.bucket_a}={bs.fmt_size(A[k])} "
              f"{a.bucket_b}={bs.fmt_size(B[k])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
