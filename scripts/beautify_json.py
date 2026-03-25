#!/usr/bin/env python3
"""Recursively beautify (pretty-print) JSON files."""

import json
import sys
from pathlib import Path


def beautify(path: Path) -> int:
    """Pretty-print a single JSON file in place. Returns 1 if modified, 0 otherwise."""
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    pretty = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if raw == pretty:
        return 0
    path.write_text(pretty, encoding="utf-8")
    print(f"  beautified: {path}")
    return 1


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file_or_folder> [...]")
        sys.exit(1)

    modified = 0
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_file() and p.suffix == ".json":
            modified += beautify(p)
        elif p.is_dir():
            for f in sorted(p.rglob("*.json")):
                modified += beautify(f)
        else:
            print(f"  skipped: {p}")

    print(f"Done. {modified} file(s) modified.")


if __name__ == "__main__":
    main()
