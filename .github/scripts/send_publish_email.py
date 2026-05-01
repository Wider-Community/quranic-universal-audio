#!/usr/bin/env python3
"""Email a reciter's requester when their data is published to the HF dataset.

Triggered after `Sync HF Dataset` succeeds. Loads
``.github/templates/emails/timestamps-done.html`` (or any template named via
``--template``), fills in placeholders, and sends via Gmail SMTP using
``GMAIL_ADDRESS`` / ``GMAIL_APP_PASSWORD`` env vars (matching the existing
``reciter_requests`` Space).

Recipient resolution:
  --to <email>      explicit override (for testing)
  (default)         look up the reciter's email in Notion via NOTION_API_KEY
                    + NOTION_REQUESTS_DB_ID. NOT YET IMPLEMENTED — script
                    exits 0 with a warning if no override is given. Wire
                    Notion later when going live to real requesters.

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
    ap.add_argument("--requester-name", default="there",
                    help="Name to greet the requester by (default: 'there')")
    ap.add_argument("--template", default="timestamps-done.html",
                    help="Template filename under .github/templates/emails/")
    ap.add_argument("--subject",
                    help="Email subject (default: derived from reciter)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print rendered email instead of sending")
    args = ap.parse_args()

    reciter = _load_reciter(args.reciter)
    name_en = reciter.get("name_en") or args.reciter

    if not args.to:
        log.warning("No --to override and Notion lookup not yet implemented; "
                    "skipping. Pass --to <email> to send.")
        return 0

    subject = args.subject or f"{name_en} is now in the dataset"
    html_body = _render(
        args.template,
        requester_name=args.requester_name,
        reciter_name=name_en,
        links_html=_build_links_html(reciter),
        issue_link="",  # only used by some templates
    )

    if args.dry_run:
        print(f"To: {args.to}\nSubject: {subject}\n\n{html_body}")
        return 0

    sender = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not sender or not password:
        log.warning("GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set; skipping send.")
        return 0

    _send(args.to, subject, html_body, sender, password)
    log.info("Sent publication email for %s to %s", args.reciter, args.to)
    return 0


if __name__ == "__main__":
    sys.exit(main())
