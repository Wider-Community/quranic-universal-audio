"""Shared visibility rules for catalog deliveries.

EveryAyah remains in the Inspector catalog for owner operations, but it is an
internal source and must not appear in public Inspector surfaces or public
release projections. Keeping the identifier here prevents individual routes
and release adapters from drifting apart.
"""

from __future__ import annotations

EVERYAYAH_CHANNEL = "everyayah"


def is_everyayah_channel(channel: str | None) -> bool:
    return isinstance(channel, str) and channel.strip().lower() == EVERYAYAH_CHANNEL
