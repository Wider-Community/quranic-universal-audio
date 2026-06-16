"""Email-notification subsystem — Flask-free.

Sends no-reply emails for the six opt-in events behind the "My notifications"
envelope modal. Storage of the opt-ins lives in ``services.db`` (keyed by email);
this package owns rendering (``templates``) + SMTP dispatch (``send``) and the
per-event recipient resolution (``emit``). Gmail credentials come from the
``GMAIL`` / ``GMAIL_PASS`` Space secrets (``secrets``); absent them the sender
logs the rendered email instead of dispatching.

Call sites import the ``emit`` functions lazily to keep this off the
state-machine import-time graph (mirrors ``services.notifications``).
"""

from __future__ import annotations

from .emit import (
    emit_github_release,
    emit_recitation_published,
    emit_request_aligned,
    emit_timestamps_regenerated,
)

__all__ = [
    "emit_github_release",
    "emit_recitation_published",
    "emit_request_aligned",
    "emit_timestamps_regenerated",
]
