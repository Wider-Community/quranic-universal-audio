#!/usr/bin/env python3
"""Email a reciter's requester when their data is published to the HF dataset.

Triggered after `Sync HF Dataset` succeeds. Loads
``.github/templates/emails/timestamps-done.html`` (or any template named via
``--template``), fills in placeholders, and sends via Gmail SMTP using
``GMAIL_ADDRESS`` / ``GMAIL_APP_PASSWORD`` env vars (matching the existing
``reciter_requests`` Space).

Recipient resolution:
  --to <email>      explicit override (for testing)
  (default)         look up the reciter's email + display name in the
                    requests Notion DB via NOTION_API_KEY +
                    NOTION_REQUESTS_DB_ID (or NOTION_DATABASE_ID).
                    No-ops with a warning if creds missing or no row matches.

Usage:
    python3 .github/scripts/send_publish_email.py \
        --reciter saad_al_ghamdi \
        --to ahmed.ibrahim8165@gmail.com
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import smtplib
import subprocess
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO_ROOT / ".github" / "templates" / "emails"
RECITERS_INDEX = REPO_ROOT / "data" / "reciters_index.json"
HF_DATASET = "hetchyy/quranic-universal-ayahs"
GH_REPO = "Wider-Community/quranic-universal-audio"

logging.basicConfig(format="%(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("send_publish_email")


def _notion_lookup(slug: str) -> tuple[str | None, str | None]:
    """Return (email, requester_name) from the Notion requests DB, or (None, None).

    Schema (matches reciter_requests/app.py:548):
      - Slug (rich_text)
      - Email (email)
      - Requester Name (title)
    """
    api_key = os.environ.get("NOTION_API_KEY")
    db_id = (os.environ.get("NOTION_REQUESTS_DB_ID")
             or os.environ.get("NOTION_DATABASE_ID"))
    if not api_key or not db_id:
        log.info("Notion creds not set; skipping lookup")
        return None, None
    try:
        import urllib.request
        body = json.dumps({
            "filter": {"property": "Slug",
                       "rich_text": {"equals": slug}},
            "page_size": 1,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.notion.com/v1/databases/{db_id}/query",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        log.warning("Notion query failed: %s", e)
        return None, None

    results = data.get("results") or []
    if not results:
        log.info("Notion: no row for slug %s", slug)
        return None, None
    props = results[0].get("properties") or {}
    email = (props.get("Email") or {}).get("email")
    title = (props.get("Requester Name") or {}).get("title") or []
    name = title[0].get("plain_text") if title else None
    return email, name


def _load_reciter(slug: str) -> dict:
    with open(RECITERS_INDEX, "r", encoding="utf-8") as f:
        idx = json.load(f)
    items = idx if isinstance(idx, list) else idx.get("reciters", [])
    for r in items:
        if isinstance(r, dict) and r.get("slug") == slug:
            return r
    raise SystemExit(f"reciter {slug!r} not found in {RECITERS_INDEX}")


def _build_links_html(reciter: dict) -> str:
    slug = reciter["slug"]
    riwayah = reciter.get("riwayah", "")
    viewer = (f"https://huggingface.co/datasets/{HF_DATASET}/viewer/"
              f"{riwayah}/{slug}")
    release = f"https://github.com/{GH_REPO}/releases/tag/{slug}-latest"
    return (
        "<ul>\n"
        f'  <li><a href="{viewer}">Browse the data on Hugging Face</a></li>\n'
        f'  <li><a href="{release}">Download the GitHub release</a></li>\n'
        "</ul>"
    )


def _timestamps_existed_at(slug: str, ref: str) -> bool:
    """Did this slug's timestamps.json exist in either audio_type at <ref>?"""
    for audio_type in ("by_ayah_audio", "by_surah_audio"):
        rel = f"data/timestamps/{audio_type}/{slug}/timestamps.json"
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{ref}:{rel}"],
            cwd=REPO_ROOT, capture_output=True,
        )
        if result.returncode == 0:
            return True
    return False


def _render(template_name: str, **fields) -> str:
    tpl_path = TEMPLATES_DIR / template_name
    if not tpl_path.exists():
        raise SystemExit(f"template not found: {tpl_path}")
    return tpl_path.read_text(encoding="utf-8").format(**fields)


def _send(to: str, subject: str, html_body: str, sender: str,
          password: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, to, msg.as_string())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reciter", required=True, help="Reciter slug")
    ap.add_argument("--to", help="Recipient email (overrides Notion lookup)")
    ap.add_argument("--requester-name",
                    help="Name to greet the requester by (default: from Notion, "
                         "else 'there')")
    ap.add_argument("--template", default="timestamps-done.html",
                    help="Template filename under .github/templates/emails/")
    ap.add_argument("--subject",
                    help="Email subject (default: derived from reciter)")
    ap.add_argument("--first-publish-only", action="store_true",
                    help="Skip if timestamps.json already existed at --before-ref")
    ap.add_argument("--before-ref",
                    help="Git ref to compare against for --first-publish-only")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print rendered email instead of sending")
    args = ap.parse_args()

    if args.first_publish_only:
        if not args.before_ref:
            log.warning("--first-publish-only requires --before-ref; skipping.")
            return 0
        if _timestamps_existed_at(args.reciter, args.before_ref):
            log.info("Not first publish for %s (already at %s); skipping email",
                     args.reciter, args.before_ref)
            return 0

    reciter = _load_reciter(args.reciter)
    name_en = reciter.get("name_en") or args.reciter

    # Resolve recipient + greeting name. CLI overrides win; otherwise fall
    # back to Notion. If neither yields anything, no-op.
    notion_email, notion_name = (None, None)
    if not args.to or not args.requester_name:
        notion_email, notion_name = _notion_lookup(args.reciter)

    to_email = args.to or notion_email
    if not to_email:
        log.warning("No recipient (no --to and no Notion match); skipping.")
        return 0
    requester_name = args.requester_name or notion_name or "there"

    subject = args.subject or f"{name_en} is now in the dataset"
    html_body = _render(
        args.template,
        requester_name=requester_name,
        reciter_name=name_en,
        links_html=_build_links_html(reciter),
        issue_link="",  # only used by some templates
    )

    if args.dry_run:
        print(f"To: {to_email}\nSubject: {subject}\n\n{html_body}")
        return 0

    sender = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not sender or not password:
        log.warning("GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set; skipping send.")
        return 0

    _send(to_email, subject, html_body, sender, password)
    log.info("Sent publication email for %s to %s", args.reciter, to_email)
    return 0


if __name__ == "__main__":
    sys.exit(main())
