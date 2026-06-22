"""Print a bucket file's contents.

bucket_cat.py catalog/audio_manifest/husary_mp3quran.json --json --bucket prod
bucket_cat.py reciters/<slug>/peaks/2.json.gz --gz --json --head 50
bucket_cat.py reciters/<slug>/audio/2.mp3 --bytes 4   # first 4 bytes (sanity peek)
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _bootstrap as bs  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("path", help="path within the bucket")
    p.add_argument("--head", type=int, default=0, help="first N lines (after decode)")
    p.add_argument(
        "--bytes",
        dest="byte_limit",
        type=int,
        default=0,
        help="dump first N bytes (binary-safe, hex)",
    )
    p.add_argument("--json", action="store_true", help="parse + pretty-print as JSON")
    p.add_argument("--gz", action="store_true", help="gunzip before processing")
    bs.add_bucket_args(p)
    a = p.parse_args()

    fs, bucket = bs.resolve(a)
    target = bs.abs_path(bucket, a.path)

    with fs.open(target, "rb") as f:
        raw = f.read()

    if a.byte_limit > 0:
        chunk = raw[: a.byte_limit]
        print(f"{len(raw)} bytes total; first {len(chunk)}:")
        print(chunk.hex(" "))
        return 0

    if a.gz:
        raw = gzip.decompress(raw)

    if a.json:
        doc = json.loads(raw.decode("utf-8"))
        text = json.dumps(doc, ensure_ascii=False, indent=2)
    else:
        text = raw.decode("utf-8", errors="replace")

    if a.head > 0:
        text = "\n".join(text.splitlines()[: a.head])
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
