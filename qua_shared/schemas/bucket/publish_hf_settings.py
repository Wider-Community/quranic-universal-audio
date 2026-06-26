"""Dataset-publishing settings — chosen by the admin in the Releases tab.

The clip-edge convention for the published dataset. Internal (within-verse)
segment boundaries are byte-exact with the post-MFA word/letter ends; only the
two OUTER edges of a row carry padded headroom, computed from MFA times (not
VAD): between verse N's last-letter end and verse N+1's first-letter start there
is a true silence; we hand ``pad_end`` ms to N's tail and ``pad_start`` ms to
N+1's lead, always leaving at least ``min_gap`` ms of silence between the two
clips. When ``pad_end + min_gap + pad_start`` would overflow the available
silence, the pads scale down proportionally (the ``pad_end : pad_start`` ratio is
preserved) so adjacent rows never leak into each other.

Threaded UI → ``AdminPublishBatchRequest.settings`` → the publish HF job env
(``PUBLISH_PAD_START`` / ``PUBLISH_PAD_END`` / ``PUBLISH_MIN_GAP``) →
``publish_hf.build_rows``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PublishHfSettings(BaseModel):
    """Clip-edge padding for dataset publishing (all in milliseconds)."""

    model_config = ConfigDict(extra="forbid")

    #: Headroom before a verse's first word (the row's leading edge).
    pad_start: int = Field(default=100, ge=0)
    #: Headroom after a verse's last word (the row's trailing edge).
    pad_end: int = Field(default=300, ge=0)
    #: Guaranteed silence kept between two adjacent verse-row clips (anti-leak).
    min_gap: int = Field(default=100, ge=0)
