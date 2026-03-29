#!/usr/bin/env python3
"""Send release notification emails to watchers.

Reads the release manifest, queries Notion for watchers of each reciter,
groups notifications per user, and sends a single email per watcher.

Usage (from release workflow):
    python scripts/notify_watchers.py --manifest dist/manifest.json --version v0.3.0
"""

import argparse
import json
import sys
import time
from pathlib import Path

# Add scripts/ to path for request_helpers
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from request_helpers import send_email, notion_get_watchers_for_targets  # noqa: E402
from config_loader import load_template  # noqa: E402

REPO_OWNER = "Wider-Community"
REPO_NAME = "quranic-universal-audio"
SPACE_URL = "https://hetchyy-quran-reciter-requests.hf.space"


def load_release_history(repo_root):
    """Load existing release history cache."""
    path = repo_root / "data" / ".release_history.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def classify_reciters(manifest, history):
    """Classify manifest reciters as new or updated based on release history."""
    new = []
    updated = []
    for rec in manifest.get("reciters", []):
        slug = rec["slug"]
        if slug not in history or "first_release" not in history[slug]:
            new.append(rec)
        else:
            # Compare hashes — if different, it's an update
            prev_hash = history[slug].get("latest_zip_sha256", "")
            curr_hash = rec.get("zip_sha256", "")
            if curr_hash and curr_hash != prev_hash:
                updated.append(rec)
            elif not prev_hash:
                # No previous hash — treat as update
                updated.append(rec)
    return new, updated


def build_email_html(watcher_name, version, release_url, unsubscribe_url,
                     new_reciters, updated_reciters):
    """Build the notification email HTML."""
    # Try loading from template, fall back to inline
    try:
        template = load_template("emails/release-notification.html")
    except Exception:
        template = None

    # Build sections
    new_html = ""
    if new_reciters:
        items = ""
        for r in new_reciters:
            name_ar = f" — {r.get('name_ar', '')}" if r.get("name_ar") else ""
            dl = f'<a href="{r["download_url"]}">Download</a> &middot; ' if r.get("download_url") else ""
            cov = r.get("coverage", {})
            cov_text = f"{cov.get('surahs', '?')} surahs, {cov.get('ayahs', '?')} ayahs" if isinstance(cov, dict) else str(cov)
            items += f"  <li><strong>{r.get('reciter_display', r['slug'])}</strong>{name_ar}<br>{dl}Coverage: {cov_text}</li>\n"
        new_html = f"<h3>New Reciters Added</h3>\n<ul>\n{items}</ul>\n"

    updated_html = ""
    if updated_reciters:
        items = ""
        for r in updated_reciters:
            name_ar = f" — {r.get('name_ar', '')}" if r.get("name_ar") else ""
            dl = f'<a href="{r["download_url"]}">Download</a> &middot; ' if r.get("download_url") else ""
            cov = r.get("coverage", {})
            cov_text = f"{cov.get('surahs', '?')} surahs, {cov.get('ayahs', '?')} ayahs" if isinstance(cov, dict) else str(cov)
            items += f"  <li><strong>{r.get('reciter_display', r['slug'])}</strong>{name_ar}<br>{dl}Coverage: {cov_text}</li>\n"
        updated_html = f"<h3>Updated Reciters</h3>\n<ul>\n{items}</ul>\n"

    body = f"""
<h2>New Release: {version}</h2>
<p>Hi {watcher_name or 'there'},</p>
<p>A new release of Quranic Universal Audio is available with updates to reciters you're watching.</p>
{new_html}
{updated_html}
<p><a href="{release_url}">View full release notes on GitHub &rarr;</a></p>
<hr style="border:none;border-top:1px solid #e0e0e0;margin:24px 0">
<p style="font-size:12px;color:#888">
  You received this because you're watching these reciters.
  <a href="{unsubscribe_url}">Unsubscribe</a> &middot;
  <a href="https://github.com/{REPO_OWNER}/{REPO_NAME}">GitHub</a>
</p>
"""
    return f'<div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto;padding:20px">{body}</div>'


def main():
    parser = argparse.ArgumentParser(description="Send release notifications to watchers")
    parser.add_argument("--manifest", required=True, help="Path to dist/manifest.json")
    parser.add_argument("--version", required=True, help="Release version (e.g., v0.3.0)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be sent without sending")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    manifest = json.loads(Path(args.manifest).read_text())
    history = load_release_history(repo_root)

    # Classify reciters
    new_reciters, updated_reciters = classify_reciters(manifest, history)
    all_changed = new_reciters + updated_reciters
    if not all_changed:
        print("No new or updated reciters in this release — no notifications to send.")
        return

    changed_slugs = [r["slug"] for r in all_changed]
    print(f"Release {args.version}: {len(new_reciters)} new, {len(updated_reciters)} updated reciters")
    print(f"  Slugs: {', '.join(changed_slugs)}")

    # Query Notion for watchers
    watchers = notion_get_watchers_for_targets(changed_slugs, "reciter")
    if not watchers:
        print("No watchers found for changed reciters — no notifications to send.")
        return

    # Group by email: {email: {name, new_reciters, updated_reciters}}
    per_user = {}
    for rec in new_reciters:
        for w in watchers.get(rec["slug"], []):
            entry = per_user.setdefault(w["email"], {"name": w["name"], "new": [], "updated": []})
            entry["new"].append(rec)
    for rec in updated_reciters:
        for w in watchers.get(rec["slug"], []):
            entry = per_user.setdefault(w["email"], {"name": w["name"], "new": [], "updated": []})
            entry["updated"].append(rec)

    print(f"Sending notifications to {len(per_user)} user(s)...")
    release_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/tag/{args.version}"

    sent = 0
    failed = 0
    for email, info in per_user.items():
        unsubscribe_url = f"{SPACE_URL}/api/unsubscribe?email={email}"
        html = build_email_html(
            watcher_name=info["name"],
            version=args.version,
            release_url=release_url,
            unsubscribe_url=unsubscribe_url,
            new_reciters=info["new"],
            updated_reciters=info["updated"],
        )
        subject = f"Quranic Universal Audio — Release {args.version}"

        if args.dry_run:
            print(f"  [DRY RUN] Would send to {email}: {subject}")
            print(f"    New: {[r['slug'] for r in info['new']]}")
            print(f"    Updated: {[r['slug'] for r in info['updated']]}")
            sent += 1
        else:
            if send_email(email, subject, html):
                sent += 1
            else:
                failed += 1
            time.sleep(1)  # Rate limit

    print(f"\nDone: {sent} sent, {failed} failed")


if __name__ == "__main__":
    main()
