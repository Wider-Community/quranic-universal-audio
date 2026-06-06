#!/usr/bin/env python3
"""Check a downloaded release for per-reciter timestamp updates.

Stdlib-only — shipped as a release asset so consumers can run it without
installing dependencies. Tells you which of the reciters you already downloaded
were refreshed in a newer release (e.g. timestamps re-aligned with an improved
model), so you don't have to re-pull everything or diff releases by hand.

Usage:
    python check_updates.py <manifest.json> [--reciters a,b,c]
                            [--json] [--sync] [--repo owner/name]
                            [--latest-file <path>] [--token <gh_token>]

``<manifest.json>`` is the dataset-level ``manifest.json`` you downloaded with
your data — keep it next to your reciter zips; it is the baseline this compares
against. The helper fetches the latest release's ``manifest.json`` from GitHub
and diffs each reciter's ``content_hash`` (the canonical change signal).

Exit code is **1 when any of your reciters changed** (and 0 when everything is
current), so a scheduled GitHub Action / CI job that runs this "fails" on a
change — GitHub then emails you with no extra wiring. Pair with ``--sync`` to
download the changed zips and refresh the local manifest automatically, turning
this into a self-updating data mirror.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

GITHUB_API = "https://api.github.com"

# Per-reciter status values returned by ``compute_updates``.
STATUS_UPDATED = "updated"  # content_hash differs from the baseline
STATUS_NEW = "newly_available"  # in the latest release, not in your baseline
STATUS_UP_TO_DATE = "up_to_date"  # content_hash matches the baseline
STATUS_REMOVED = "removed"  # in your baseline, gone from the latest release
STATUS_UNKNOWN = "unknown"  # requested via --reciters but in neither manifest


def compute_updates(
    baseline: dict, latest: dict, reciters: list[str] | None = None
) -> dict:
    """Diff a baseline release manifest against the latest, per reciter.

    ``baseline`` and ``latest`` are dataset-level ``manifest.json`` dicts
    (``{release_version, recitations: {slug: {content_hash, ts_version,
    zip_url, ...}}}``). The comparison key is ``content_hash`` — the cut job
    derives it from each reciter's letter-tier + catalog bytes, so it changes
    iff the reciter's shipped timestamps or catalog changed.

    ``reciters`` optionally scopes the check to specific slugs (the reciters you
    actually use). When omitted, every reciter in the BASELINE is checked — i.e.
    "did anything I already have change" — and reciters newly added to the
    release are not reported unless you name them explicitly.

    Returns::

        {
          "baseline_version": str | None,
          "latest_version":   str | None,
          "checked":          int,
          "updates":   [{"slug", "status", "ts_version", "zip_url"}, ...],
              # status is "updated" or "newly_available"
          "up_to_date": [slug, ...],
          "removed":    [slug, ...],
          "unknown":    [slug, ...],   # only via --reciters typos
        }

    ``updates`` and ``removed`` together are the actionable changes; a caller
    exits non-zero when either is non-empty.
    """
    base_recs = baseline.get("recitations") or {}
    latest_recs = latest.get("recitations") or {}
    scope = list(reciters) if reciters else sorted(base_recs)

    updates: list[dict] = []
    up_to_date: list[str] = []
    removed: list[str] = []
    unknown: list[str] = []

    for slug in scope:
        in_base = slug in base_recs
        in_latest = slug in latest_recs
        if in_latest:
            new = latest_recs[slug]
            if not in_base:
                status = STATUS_NEW
            elif base_recs[slug].get("content_hash") != new.get("content_hash"):
                status = STATUS_UPDATED
            else:
                up_to_date.append(slug)
                continue
            updates.append(
                {
                    "slug": slug,
                    "status": status,
                    "ts_version": new.get("ts_version"),
                    "zip_url": new.get("zip_url"),
                }
            )
        elif in_base:
            removed.append(slug)
        else:
            unknown.append(slug)

    return {
        "baseline_version": baseline.get("release_version"),
        "latest_version": latest.get("release_version"),
        "checked": len(scope),
        "updates": updates,
        "up_to_date": up_to_date,
        "removed": removed,
        "unknown": unknown,
    }


def has_changes(result: dict) -> bool:
    """True when the diff found anything actionable (updated/new/removed)."""
    return bool(result["updates"] or result["removed"])


# ---------------------------------------------------------------------------
# GitHub fetch (stdlib urllib only).
# ---------------------------------------------------------------------------


def repo_from_manifest(manifest: dict) -> str | None:
    """Derive ``owner/name`` from any reciter's ``zip_url`` in the manifest.

    A ``zip_url`` looks like
    ``https://github.com/<owner>/<repo>/releases/download/<tag>/<slug>.zip`` —
    the owner/repo are the two path parts after ``github.com``.
    """
    for rec in (manifest.get("recitations") or {}).values():
        url = rec.get("zip_url") or ""
        marker = "github.com/"
        if marker in url:
            parts = url.split(marker, 1)[1].split("/")
            if len(parts) >= 2 and parts[0] and parts[1]:
                return f"{parts[0]}/{parts[1]}"
    return None


def _get_json(url: str, token: str | None) -> dict | list:
    """GET a URL and parse JSON. Raises on HTTP / decode error."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "quranic-universal-audio-check-updates",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def fetch_latest_manifest(repo: str, token: str | None = None) -> dict:
    """Fetch the latest release's ``manifest.json`` for ``owner/name``.

    Uses the GitHub API ``releases/latest``; falls back to the newest entry of
    ``releases?per_page=1`` (which, unlike ``/latest``, also surfaces a release
    flagged as a pre-release). Returns the parsed manifest dict.
    """
    try:
        release = _get_json(f"{GITHUB_API}/repos/{repo}/releases/latest", token)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        listing = _get_json(f"{GITHUB_API}/repos/{repo}/releases?per_page=1", token)
        if not listing:
            raise RuntimeError(f"{repo} has no releases") from exc
        release = listing[0]

    assets = release.get("assets") or [] if isinstance(release, dict) else []
    for asset in assets:
        if asset.get("name") == "manifest.json":
            return _get_json(asset["browser_download_url"], token)
    raise RuntimeError(f"latest release of {repo} has no manifest.json asset")


def _download(url: str, dest: Path, token: str | None) -> None:
    """Download ``url`` to ``dest`` (streamed)."""
    headers = {"User-Agent": "quranic-universal-audio-check-updates"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as resp, dest.open("wb") as fh:
        while chunk := resp.read(1 << 16):
            fh.write(chunk)


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def _print_human(result: dict) -> None:
    base = result["baseline_version"] or "?"
    latest = result["latest_version"] or "?"
    print(f"Checked {result['checked']} reciter(s) against the latest release.")
    print(f"  you have: {base}    latest: {latest}")
    print()
    if not has_changes(result):
        print(f"All {result['checked']} reciter(s) are up to date.")
        return
    for u in result["updates"]:
        label = "updated" if u["status"] == STATUS_UPDATED else "newly available"
        print(f"  ~ {u['slug']}  ({label}; ts {u['ts_version']})")
        print(f"      {u['zip_url']}")
    for slug in result["removed"]:
        print(f"  - {slug}  (no longer in the latest release)")
    for slug in result["unknown"]:
        print(f"  ? {slug}  (not found in either release — check the slug)")
    n = len(result["updates"]) + len(result["removed"])
    print()
    print(f"{n} change(s). Re-download with --sync, or fetch the URLs above.")


def _sync(result: dict, manifest_path: Path, latest: dict, token: str | None) -> None:
    """Download changed/new zips next to the manifest, then refresh the manifest."""
    out_dir = manifest_path.parent
    for u in result["updates"]:
        if not u["zip_url"]:
            continue
        dest = out_dir / f"{u['slug']}.zip"
        print(f"  downloading {dest.name} ...")
        _download(u["zip_url"], dest, token)
    manifest_path.write_text(
        json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  refreshed {manifest_path.name} to {latest.get('release_version')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check a downloaded release manifest for per-reciter updates"
    )
    parser.add_argument(
        "manifest", type=Path, help="Path to the manifest.json you downloaded (baseline)"
    )
    parser.add_argument(
        "--reciters", help="Comma-separated slugs to check (default: all in your manifest)"
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument(
        "--sync", action="store_true", help="Download changed zips + refresh the manifest"
    )
    parser.add_argument("--repo", help="owner/name override (default: read from the manifest)")
    parser.add_argument(
        "--latest-file", type=Path, help="Compare against a local manifest instead of GitHub"
    )
    parser.add_argument("--token", help="GitHub token to raise the API rate limit (optional)")
    args = parser.parse_args(argv)

    if not args.manifest.exists():
        print(f"error: {args.manifest} does not exist", file=sys.stderr)
        return 2
    try:
        baseline = json.loads(args.manifest.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read {args.manifest}: {exc}", file=sys.stderr)
        return 2

    if args.latest_file:
        try:
            latest = json.loads(args.latest_file.read_bytes())
        except (OSError, json.JSONDecodeError) as exc:
            print(f"error: cannot read {args.latest_file}: {exc}", file=sys.stderr)
            return 2
    else:
        repo = args.repo or repo_from_manifest(baseline)
        if not repo:
            print(
                "error: could not determine the GitHub repo from the manifest; "
                "pass --repo owner/name",
                file=sys.stderr,
            )
            return 2
        try:
            latest = fetch_latest_manifest(repo, args.token)
        except (urllib.error.URLError, RuntimeError) as exc:
            print(f"error: could not fetch the latest release: {exc}", file=sys.stderr)
            return 3

    reciters = [s.strip() for s in args.reciters.split(",") if s.strip()] if args.reciters else None
    result = compute_updates(baseline, latest, reciters)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(result)

    if args.sync and result["updates"]:
        _sync(result, args.manifest, latest, args.token)

    return 1 if has_changes(result) else 0


if __name__ == "__main__":
    sys.exit(main())
