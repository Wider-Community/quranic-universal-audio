"""Delete a bucket file or directory.

bucket_rm.py debug/note.txt
bucket_rm.py reciters/<dead-slug> --recursive --bucket prod --yes-prod

A recursive delete enumerates under the directory's own trailing slash rather than
handing the path to ``fs.rm(..., recursive=True)``. The bucket filesystem expands a
directory path as a raw string prefix, so that call deletes every sibling the name
extends into: ``reciters/<slug>`` would take ``reciters/<slug>_bnd`` with it. The
count is resolved before the confirmation so the operator sees the real blast radius.
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

    fs, bucket = bs.resolve(a)
    target = bs.abs_path(bucket, a.path)

    info = fs.info(target)
    if info.get("type") != "directory":
        bs.confirm_mutation(a, f"delete {a.path}")
        fs.rm_file(target)
        print(f"deleted {target}")
        return 0

    if not a.recursive:
        print(f"refusing to delete directory {target} without --recursive", file=sys.stderr)
        return 2
    # find() answers without the hf:// scheme, so both sides are stripped before the
    # boundary test — comparing a scheme-carrying prefix matches nothing and reads as
    # an empty directory.
    prefix = fs._strip_protocol(target).rstrip("/") + "/"
    victims = [path for path in fs.find(prefix) if fs._strip_protocol(path).startswith(prefix)]
    if not victims:
        print(f"refusing to delete {target}: no objects under it", file=sys.stderr)
        return 2
    bs.confirm_mutation(a, f"delete {a.path} ({len(victims)} object(s))")
    for path in victims:
        fs.rm_file(path)
    print(f"deleted {target} ({len(victims)} object(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
