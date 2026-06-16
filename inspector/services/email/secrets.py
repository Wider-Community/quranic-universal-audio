"""Gmail SMTP credential access.

Reads the ``GMAIL`` / ``GMAIL_PASS`` Space secrets (an account address + an app
password). Returns ``None`` when either is unset — the dev/no-op path, where the
sender logs the rendered email instead of dispatching. No placeholder guard
beyond non-empty: a bad password simply fails the SMTP login, logged best-effort.
"""

from __future__ import annotations

import os


def get_gmail_credentials() -> tuple[str, str] | None:
    """``(address, app_password)`` when both secrets are set, else ``None``."""
    user = os.environ.get("GMAIL", "").strip()
    password = os.environ.get("GMAIL_PASS", "").strip()
    if not user or not password:
        return None
    return user, password
