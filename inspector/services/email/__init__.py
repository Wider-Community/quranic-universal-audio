"""Email-notification subsystem — Flask-free.

Sends no-reply emails for the six opt-in events behind the "My notifications"
envelope modal. Storage of the opt-ins lives in ``services.db`` (keyed by email);
this package owns rendering (``templates``) + HTTPS dispatch (``send``, via the
Brevo transactional API — HF Spaces block outbound SMTP) and the per-event
recipient resolution (``emit``). The API key comes from the ``BREVO_API_KEY``
Space secret; absent it the sender logs the rendered email instead of dispatching.

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
