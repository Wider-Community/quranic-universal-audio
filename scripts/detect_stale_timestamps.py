#!/usr/bin/env python3
"""Detect stale timestamps by comparing segments.json versions in git.

Compares the before/after versions of a segments.json file and outputs
the affected surahs and changed verse keys. Used by the CI workflow to
determine which surahs need MFA re-extraction.

Usage:
    python scripts/detect_stale_timestamps.py <before_ref> <segments_path>

    before_ref:    Git ref for the old version (e.g. HEAD~1, abc123)
    segments_path: Path to segments.json (current working tree version)

Output (stdout, key=value lines):
    surahs=1,37,114
    changed=1:1,37:151,37:152
    deleted=37:151:3-37:152:2

Exit codes:
    0 — changes detected (output written)
    1 — no changes detected
    2 — error (e.g. file not found in git)
"""

import json
import subprocess
import sys


def _sort_key(key: str) -> tuple:
    """Sort key for verse keys like '1:1', '37:151:3-37:152:2'."""
    parts = key.split(":")[0].split("-")[0], key.split(":")[1].split("-")[0] if ":" in key else "0"
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return (999, 999)


def detect(before_ref: str, segments_path: str) -> tuple[set[str], set[str], set[str]]:
    """Compare old vs new segments.json, return (surahs, changed, deleted)."""
    # Load old version from git
    try:
        old_raw = subprocess.check_output(
            ["git", "show", f"{before_ref}:{segments_path}"],
            stderr=subprocess.DEVNULL,
        )
        old = json.loads(old_raw)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        # File didn't exist before — everything is new
        old = {}

    # Load new version from working tree
    with open(segments_path, "r", encoding="utf-8") as f:
        new = json.loads(f.read())

    old_keys = {k for k in old if k != "_meta"}
    new_keys = {k for k in new if k != "_meta"}

    added = new_keys - old_keys
    deleted = old_keys - new_keys
    modified = {k for k in old_keys & new_keys if old[k] != new[k]}

    changed = added | modified
    # Derive affected surahs from all changed/deleted keys
    surahs = {k.split(":")[0].split("-")[0] for k in changed | deleted}

    return surahs, changed, deleted


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <before_ref> <segments_path>", file=sys.stderr)
        sys.exit(2)

    before_ref = sys.argv[1]
    segments_path = sys.argv[2]

    surahs, changed, deleted = detect(before_ref, segments_path)

    if not surahs:
        sys.exit(1)

    print(f"surahs={','.join(sorted(surahs, key=lambda s: int(s) if s.isdigit() else 999))}")
    print(f"changed={','.join(sorted(changed, key=_sort_key))}")
    if deleted:
        print(f"deleted={','.join(sorted(deleted, key=_sort_key))}")


if __name__ == "__main__":
    main()
