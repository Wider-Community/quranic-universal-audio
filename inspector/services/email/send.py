"""HTTPS email dispatch via Brevo — fire-and-forget, best-effort.

``send`` submits the actual network work to a small ``ThreadPoolExecutor`` so a
transition / job-completion is never blocked on it. Delivery goes over HTTPS
(Brevo's transactional REST API, ``POST /v3/smtp/email``) because HF Spaces block
outbound SMTP on every port — a direct ``smtplib`` connection returns "Network is
unreachable" and silently never delivers. Auth is the ``BREVO_API_KEY`` secret;
the From address is the Brevo-verified sender (``config.EMAIL_FROM_ADDRESS``).

When the key is absent (local dev), the fully rendered email is logged instead of
dispatched, so the whole flow is exercisable without secrets. Failures are logged
and swallowed — a lost notification email must never break the motivating write.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import config

logger = logging.getLogger("email")

_BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"

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
        api_key = config.BREVO_API_KEY
        body_text = text or html_to_text(html)
        if not api_key:
            logger.info(
                "email (dev, not sent) → %s | subject=%s\n%s",
                to,
                subject,
                body_text,
            )
            return
        payload = {
            "sender": {"name": config.EMAIL_FROM_NAME, "email": config.EMAIL_FROM_ADDRESS},
            "to": [{"email": to}],
            "subject": subject,
            "htmlContent": html,
            "textContent": body_text,
        }
        req = urllib.request.Request(
            _BREVO_ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "api-key": api_key,
                "content-type": "application/json",
                "accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
        logger.info("email sent → %s | subject=%s", to, subject)
    except urllib.error.HTTPError as e:  # 4xx/5xx — surface Brevo's reason
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        logger.error(
            "email send failed → %s | subject=%s | HTTP %s %s", to, subject, e.code, detail
        )
    except Exception:  # noqa: BLE001 — best-effort; never raise into the caller
        logger.exception("email send failed → %s | subject=%s", to, subject)
