"""Delete a bucket file or directory.

bucket_rm.py debug/note.txt
bucket_rm.py reciters/<dead-slug> --recursive --bucket prod --yes-prod
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
    p.add_argument("path", help="bucket path to delete")
    p.add_argument("--recursive", action="store_true", help="required for directories")
    bs.add_bucket_args(p)
    a = p.parse_args()
    bs.confirm_mutation(a, f"delete {a.path}")

    fs, bucket = bs.resolve(a)
    target = bs.abs_path(bucket, a.path)

    info = fs.info(target)
    if info.get("type") == "directory":
        if not a.recursive:
            print(f"refusing to delete directory {target} without --recursive", file=sys.stderr)
            return 2
        fs.rm(target, recursive=True)
    else:
        fs.rm_file(target)
    print(f"deleted {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
