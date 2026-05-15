#!/usr/bin/env python3
"""Find the segments PR for a reciter slug, returning its number on stdout.

PRs are titled with the reciter's display name (e.g. "feat: add segments
for Saad Al-Ghamdi"), not the slug. The slug only appears reliably in the
matching request issue's body (`**Slug:** <slug>`), and the PR body
references that issue (`Ref #<num>`).

Strategy:
  1. Find the request issue by searching for `**Slug:** <slug>` in body.
  2. From the issue, get the display name (issue title minus `[request] `).
  3. Search PRs by issue number (`#<num>`) and by display name — both
     in title and full-text. Merge results, dedupe.
  4. Pick the most recent (mergedAt, createdAt desc) whose changed files
     include data/recitation_segments/<slug>/segments.json.

Slug-only search is kept as a final fallback for legacy PRs that did
mention the slug. Exits 0 with empty stdout if no match — caller decides
whether that is fatal.
"""
import argparse
import json
import re
import subprocess
import sys


def _run_json(cmd: list[str]) -> list | dict | None:
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if out.returncode != 0 or not out.stdout.strip():
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


def _find_request_issue(slug: str, limit: int) -> tuple[int, str] | None:
    """Return (issue_number, display_name) for the reciter slug, or None.

    Searches issues whose body contains `**Slug:** <slug>`. Picks the most
    recent. Display name = issue title with leading `[request] ` stripped.
    """
    cmd = [
        "gh", "issue", "list",
        "--state", "all",
        "--search", f'"**Slug:** {slug}" in:body',
        "--limit", str(limit),
        "--json", "number,title,body,createdAt",
    ]
    issues = _run_json(cmd) or []
    if not issues:
        return None
    issues.sort(key=lambda i: i.get("createdAt") or "", reverse=True)
    for issue in issues:
        body = issue.get("body") or ""
        if re.search(rf"\*\*Slug:\*\*\s*{re.escape(slug)}\b", body):
            title = (issue.get("title") or "").strip()
            display = re.sub(r"^\s*\[request\]\s*", "", title, flags=re.I)
            return int(issue["number"]), display
    return None


def _gh_pr_search(query: str, limit: int) -> list[dict]:
    cmd = [
        "gh", "pr", "list",
        "--state", "all",
        "--search", query,
        "--limit", str(limit),
        "--json", "number,title,state,mergedAt,createdAt",
    ]
    return _run_json(cmd) or []


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


def _dedupe(prs: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for pr in prs:
        n = pr.get("number")
        if n and n not in seen:
            seen.add(n)
            out.append(pr)
    return out


def find(slug: str, limit: int = 50) -> int | None:
    candidates: list[dict] = []

    issue = _find_request_issue(slug, limit)
    if issue is not None:
        issue_num, display_name = issue
        # Most reliable: PR explicitly references the issue number.
        candidates += _gh_pr_search(f"#{issue_num}", limit)
        # Display name in title (PR generator uses "feat: add segments for <name>").
        if display_name:
            candidates += _gh_pr_search(f'"{display_name}" in:title', limit)
            candidates += _gh_pr_search(f'"{display_name}"', limit)

    # Legacy fallback: slug literally in PR title/body.
    candidates += _gh_pr_search(f"{slug} in:title", limit)
    candidates += _gh_pr_search(slug, limit)

    for pr in _sort_recent_first(_dedupe(candidates)):
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
