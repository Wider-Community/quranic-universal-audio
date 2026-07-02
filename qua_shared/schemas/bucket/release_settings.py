"""Release settings — chosen by the admin in the Releases tab, applied to BOTH
release channels (the HF dataset publish AND the GitHub release cut).

The clip-edge convention. Internal (within-verse) segment boundaries are
byte-exact with the post-MFA word/letter ends; only the two OUTER edges of a
verse carry padded headroom, computed from MFA times (not VAD): between verse
N's last-letter end and verse N+1's first-letter start there is a true silence;
we hand ``pad_end`` ms to N's tail and ``pad_start`` ms to N+1's lead, always
leaving at least ``min_gap`` ms of silence between the two clips. When
``pad_end + min_gap + pad_start`` would overflow the available silence, the pads
scale down proportionally (the ``pad_end : pad_start`` ratio is preserved) so
adjacent clips never leak into each other.

Both channels reconstruct the SAME verse window from these knobs
(``qua_shared.verse_layout.build_verse_layouts``): the HF dataset publishes the
clip-relative view + sliced audio, the GH release publishes the source-relative
verse bound. Threaded UI → ``AdminPublishBatchRequest.settings`` /
``AdminCutReleaseRequest.settings`` → both jobs' env (``PUBLISH_PAD_START`` /
``PUBLISH_PAD_END`` / ``PUBLISH_MIN_GAP``) → ``build_verse_layouts``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReleaseSettings(BaseModel):
    """Clip-edge padding for both release channels (all in milliseconds)."""

    model_config = ConfigDict(extra="forbid")

    #: Headroom before a verse's first word (the clip's leading edge).
    pad_start: int = Field(default=100, ge=0)
    #: Headroom after a verse's last word (the clip's trailing edge).
    pad_end: int = Field(default=300, ge=0)
    #: Guaranteed silence kept between two adjacent verse clips (anti-leak).
    min_gap: int = Field(default=100, ge=0)


#: Back-compat alias (the settings were "HF publish"-only before they governed
#: the GH release too). Prefer ``ReleaseSettings``.
PublishHfSettings = ReleaseSettings
