"""Write a single file to the bucket.

bucket_put.py reciters/<slug>/audio/_done.json --json '{"schema_version":1,"total_chapters":114}'
bucket_put.py debug/note.txt --text 'one-line note'
bucket_put.py reciters/<slug>/detailed.json --file ./detailed.json --bucket prod --yes-prod
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _bootstrap as bs  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("path", help="destination path within the bucket")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", help="literal string content")
    src.add_argument("--file", help="local file path to upload")
    src.add_argument("--json", help="JSON literal (will be re-serialized)")
    bs.add_bucket_args(p)
    a = p.parse_args()
    bs.confirm_mutation(a, f"write {a.path}")

    if a.text is not None:
        body = a.text.encode("utf-8")
    elif a.json is not None:
        body = json.dumps(json.loads(a.json), ensure_ascii=False).encode("utf-8")
    else:
        body = Path(a.file).read_bytes()

    fs, bucket = bs.resolve(a)
    target = bs.abs_path(bucket, a.path)
    with fs.open(target, "wb") as f:
        f.write(body)
    print(f"wrote {len(body)} bytes → {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
