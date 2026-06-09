"""Per-user notification emission for the Dashboard "My Notifications" rail.

Resolves which user an event should notify and materializes a row via
``repo_notifications``. See ``emit`` for the two entry points
(``emit_for_event`` for lifecycle/intake events, ``notify_flag_reply`` for
segment-flag replies) and ``docs/reference/notifications.md``.
"""

from __future__ import annotations

from .emit import emit_for_event, notify_flag_reply

__all__ = ["emit_for_event", "notify_flag_reply"]
