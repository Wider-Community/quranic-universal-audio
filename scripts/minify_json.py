#!/usr/bin/env python3
"""Recursively minify JSON files (single-line, no extra whitespace)."""

import json
import sys
from pathlib import Path


def minify(path: Path) -> int:
    """Minify a single JSON file in place. Returns 1 if modified, 0 otherwise."""
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    compact = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    if raw == compact:
        return 0
    path.write_text(compact, encoding="utf-8")
    print(f"  minified: {path}")
    return 1


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file_or_folder> [...]")
        sys.exit(1)

    modified = 0
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_file() and p.suffix == ".json":
            modified += minify(p)
        elif p.is_dir():
            for f in sorted(p.rglob("*.json")):
                modified += minify(f)
        else:
            print(f"  skipped: {p}")

    print(f"Done. {modified} file(s) modified.")


if __name__ == "__main__":
    main()
