"""Pure path-string helpers for the bucket layout.

No I/O. No backend coupling. Single source for the on-bucket layout
documented in docs/planning/inspector-deploy/v2/inspector-data-storage.md §3.

Paths are returned as POSIX strings (forward slashes) regardless of host OS —
that's the wire format used by ``huggingface_hub.upload_file`` and the
``hf-mount`` driver. ``FilesystemBackend`` translates to native paths.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

WipOrPublished = Literal["wip", "published"]


def state_path() -> str:
    return "state/reciter_state.json"


def catalog_path() -> str:
    return "catalog/reciter_catalog.json"


def audio_durations_path() -> str:
    return "catalog/audio_durations.json"


def audio_manifest_path(slug: str) -> str:
    return f"catalog/audio_manifest/{slug}.json"


def roles_path() -> str:
    return "access/inspector_roles.json"


def audit_partition_path(ts: datetime) -> str:
    """Per-month audit partition path (UTC)."""
    return f"audit/{ts.year:04d}-{ts.month:02d}.jsonl"


def audit_meta_path() -> str:
    return "audit/_meta.json"


def activity_state_path() -> str:
    """Per-user dismissals + global tombstones for the activity rails."""
    return "activity/state.json"


def pending_requests_path() -> str:
    """Open user requests awaiting acceptance/rejection (one entry per slug)."""
    return "requests/pending.json"


def completed_requests_path() -> str:
    """Archive of accepted requests — written when ``reciter.alignment_completed`` fires."""
    return "requests/completed.json"


def returned_requests_path() -> str:
    """Archive of soft-rejected requests — written when ``reciter.request_rejected_soft`` fires."""
    return "requests/returned.json"


def discarded_requests_path() -> str:
    """Archive of hard-rejected requests — written when ``reciter.request_rejected_hard`` fires."""
    return "requests/discarded.json"


def reciter_dir(slug: str, kind: WipOrPublished) -> str:
    return f"{kind}/{slug}"


def reciter_file(slug: str, kind: WipOrPublished, name: str) -> str:
    return f"{kind}/{slug}/{name}"


def segments_path(slug: str, kind: WipOrPublished) -> str:
    return reciter_file(slug, kind, "segments.json")


def detailed_path(slug: str, kind: WipOrPublished) -> str:
    return reciter_file(slug, kind, "detailed.json")


def edit_history_path(slug: str, kind: WipOrPublished) -> str:
    return reciter_file(slug, kind, "edit_history.jsonl")


def edit_history_peaks_path(slug: str, kind: WipOrPublished) -> str:
    return reciter_file(slug, kind, "edit_history_peaks.jsonl")


def low_confidence_path(slug: str, kind: WipOrPublished) -> str:
    return reciter_file(slug, kind, "low_confidence_v2.json")


def auto_split_path(slug: str, kind: WipOrPublished) -> str:
    """Auto-split cursor sidecar — per-seg precomputed cursors + refs.

    Written offline by ``scripts/lib/auto_split_precompute.py`` once segments
    are finalised; read at boot by ``services/data_loader.load_auto_split``.
    Replaces the runtime MFA Space call the inspector used to make on every
    Auto Split button click.
    """
    return reciter_file(slug, kind, "auto_split_v1.json")


def published_timestamps_path(slug: str, chapter: str | int) -> str:
    """Timestamps live only under ``published/<slug>/timestamps/`` — not wip."""
    return f"published/{slug}/timestamps/{chapter}.json"


def prefetched_audio_dir(slug: str) -> str:
    return f"wip/{slug}/audio"


def prefetched_audio_path(slug: str, chapter: str | int) -> str:
    """MP3 written by the audio_prefetch worker for in-review reciters."""
    return f"wip/{slug}/audio/{chapter}.mp3"


def prefetched_peaks_dir(slug: str) -> str:
    return f"wip/{slug}/peaks"


def prefetched_peaks_path(slug: str, chapter: str | int) -> str:
    """Peaks JSON paired with the prefetched audio for fast first paint."""
    return f"wip/{slug}/peaks/{chapter}.json"


def prefetch_done_marker_path(slug: str) -> str:
    """Sentinel written atomically last; presence ⇒ prefetch fully completed."""
    return f"wip/{slug}/audio/_done.json"


PER_RECITER_FILES: tuple[str, ...] = (
    "segments.json",
    "detailed.json",
    "edit_history.jsonl",
    "edit_history_peaks.jsonl",
    "low_confidence_v2.json",
    "auto_split_v1.json",
)
