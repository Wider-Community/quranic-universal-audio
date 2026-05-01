#!/usr/bin/env python3
"""Find the segments PR for a reciter slug, returning its number on stdout.

Strategy: search PRs (any state) by reciter slug, then sort the matches
locally by mergedAt (then createdAt) descending and pick the most recent
one whose changed files include data/recitation_segments/<slug>/segments.json.
Falls back to a full-text search if title-search returns nothing. Exits 0
with empty stdout if no match — the caller decides whether that is fatal.
"""
import argparse
import json
import subprocess
import sys


def _gh_pr_search(slug: str, in_title: bool, limit: int) -> list[dict]:
    query = f"{slug} in:title" if in_title else slug
    cmd = [
        "gh", "pr", "list",
        "--state", "all",
        "--search", query,
        "--limit", str(limit),
        "--json", "number,title,state,mergedAt,createdAt",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if out.returncode != 0 or not out.stdout.strip():
        return []
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return []


def _pr_changes_segments(pr_number: int, slug: str) -> bool:
    """Confirm the PR changed data/recitation_segments/<slug>/segments.json."""
    cmd = ["gh", "pr", "view", str(pr_number), "--json", "files",
           "-q", ".files[].path"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        return False
    target = f"data/recitation_segments/{slug}/segments.json"
    return any(line.strip() == target for line in out.stdout.splitlines())


def _sort_recent_first(prs: list[dict]) -> list[dict]:
    return sorted(
        prs,
        key=lambda p: (p.get("mergedAt") or "", p.get("createdAt") or ""),
        reverse=True,
    )


def find(slug: str, limit: int = 50) -> int | None:
    candidates = _gh_pr_search(slug, in_title=True, limit=limit)
    if not candidates:
        candidates = _gh_pr_search(slug, in_title=False, limit=limit)
    for pr in _sort_recent_first(candidates):
        n = pr.get("number")
        if n and _pr_changes_segments(n, slug):
            return n
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug", help="Reciter slug (directory name)")
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()
    pr = find(args.slug, limit=args.limit)
    if pr is None:
        return 0
    print(pr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
