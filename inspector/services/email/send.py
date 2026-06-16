"""SMTP dispatch — fire-and-forget, best-effort.

``send`` builds a multipart (plaintext + HTML) message and submits the actual
SMTP work to a small ``ThreadPoolExecutor`` so a transition / job-completion is
never blocked on the network. When Gmail credentials are absent (dev), the fully
rendered email is logged instead of dispatched, so the whole flow is exercisable
without secrets. Failures are logged and swallowed — a lost notification email
must never break the motivating write.
"""

from __future__ import annotations

import logging
import re
import smtplib
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage

import config

from .secrets import get_gmail_credentials

logger = logging.getLogger("email")

# Single shared pool — single-worker app, low volume; 2 threads bound a fan-out.
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="email-send")

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\n[ \t]+")


def html_to_text(html: str) -> str:
    """Crude HTML→text for the plaintext alternative: drop tags, unescape, trim.
    The templates are short and link-light, so this is sufficient."""
    import html as _html

    text = re.sub(r"<\s*br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</\s*p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub("", text)
    text = _html.unescape(text)
    text = _WS_RE.sub("\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def send(to: str, subject: str, html: str, text: str | None = None) -> None:
    """Queue one email for delivery (returns immediately)."""
    _pool.submit(_deliver, to, subject, html, text)


def _deliver(to: str, subject: str, html: str, text: str | None) -> None:
    try:
        creds = get_gmail_credentials()
        body_text = text or html_to_text(html)
        if creds is None:
            logger.info(
                "email (dev, not sent) → %s | subject=%s\n%s",
                to,
                subject,
                body_text,
            )
            return
        address, password = creds
        msg = EmailMessage()
        msg["From"] = f"{config.EMAIL_FROM_NAME} <{address}>"
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body_text)
        msg.add_alternative(html, subtype="html")
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(address, password)
            smtp.send_message(msg)
        logger.info("email sent → %s | subject=%s", to, subject)
    except Exception:  # noqa: BLE001 — best-effort; never raise into the caller
        logger.exception("email send failed → %s | subject=%s", to, subject)
