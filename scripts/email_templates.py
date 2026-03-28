"""
HTML email templates for the reciter request automation pipeline.

Each function returns (subject, html_body).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from config_loader import load_template

FOOTER = """
<hr style="border:none;border-top:1px solid #e0e0e0;margin:24px 0">
<p style="font-size:12px;color:#888">
  Qur'anic Universal Audio &mdash;
  <a href="https://github.com/Wider-Community/quranic-universal-audio">GitHub</a>
</p>
"""


def _wrap(body_html, issue_url=None):
    """Wrap content in a simple HTML email layout."""
    link = ""
    if issue_url:
        link = f'<p>Track this request: <a href="{issue_url}">{issue_url}</a></p>'
    return f"""
<div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto;padding:20px">
{body_html}
{link}
{FOOTER}
</div>
"""


def email_receipt(reciter_name, requester_name, issue_url):
    """Confirmation email sent when a request is approved for processing."""
    subject = f"Your request for {reciter_name} has been received"
    body = load_template("emails/receipt", ext="html").format(
        requester_name=requester_name,
        reciter_name=reciter_name,
    )
    return subject, _wrap(body, issue_url)


def email_rejected_non_hafs(reciter_name, requester_name, riwayah, issue_url):
    """Rejection email for non-Hafs-an-Asim riwayah."""
    subject = f"Update on your request for {reciter_name}"
    body = load_template("emails/rejected-non-hafs", ext="html").format(
        requester_name=requester_name,
        reciter_name=reciter_name,
        riwayah=riwayah,
    )
    return subject, _wrap(body, issue_url)


def email_rejected_duplicate(reciter_name, requester_name, existing_issue_url, existing_status, issue_url):
    """Rejection email when a duplicate request already exists."""
    subject = f"Update on your request for {reciter_name}"
    body = load_template("emails/rejected-duplicate", ext="html").format(
        requester_name=requester_name,
        reciter_name=reciter_name,
        existing_status=existing_status,
        existing_issue_url=existing_issue_url,
    )
    return subject, _wrap(body, issue_url)


def email_rejected_already_processed(reciter_name, requester_name, issue_url):
    """Rejection email when a reciter is already fully processed."""
    subject = f"Update on your request for {reciter_name}"
    body = load_template("emails/rejected-already-processed", ext="html").format(
        requester_name=requester_name,
        reciter_name=reciter_name,
    )
    return subject, _wrap(body, issue_url)


def email_segments_ready(reciter_name, requester_name, issue_url, pr_url=""):
    """Email sent when segments are extracted and ready for review."""
    subject = f"Segments ready for {reciter_name} — review needed"
    pr_link = f'<p>Pull request: <a href="{pr_url}">{pr_url}</a></p>' if pr_url else ""
    pr_number = pr_url.split("/")[-1] if pr_url else "&lt;PR_NUMBER&gt;"
    body = load_template("emails/segments-ready", ext="html").format(
        requester_name=requester_name,
        reciter_name=reciter_name,
        pr_link=pr_link,
        pr_number=pr_number,
    )
    return subject, _wrap(body, issue_url)


def email_timestamps_done(reciter_name, requester_name, issue_url,
                          dataset_url="", release_url=""):
    """Email sent when timestamps are fully extracted."""
    subject = f"{reciter_name} is now fully processed"

    links_html = ""
    if dataset_url:
        links_html += f'<p><strong>Dataset:</strong> <a href="{dataset_url}">View on HuggingFace</a></p>\n'
    if release_url:
        links_html += f'<p><strong>Release:</strong> <a href="{release_url}">Download release assets</a></p>\n'

    body = load_template("emails/timestamps-done", ext="html").format(
        requester_name=requester_name,
        reciter_name=reciter_name,
        links_html=links_html,
    )
    return subject, _wrap(body, issue_url)
