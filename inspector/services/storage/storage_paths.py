"""Pure path-string helpers for the bucket layout.

No I/O. No backend coupling. Single source for the on-bucket layout
documented in docs/planning/inspector-deploy/v2/inspector-data-storage.md §3.

IMPORTANT: The 7 legacy JSON stores (state, catalog, access, pending_requests,
request_archive shards, activity_state) and append-only audit JSONL are now
READ-ONLY backups. The SQLite database (``inspector.db``, uploaded whole-file
to the bucket after each committed write) is the sole source of truth.
Migration is one-shot; these helpers remain to support test fixtures and the
migration script itself.

Per-reciter CONTENT path helpers (detailed, segments, edit_history, peaks, audio,
etc.) are still actively used and unchanged.

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


def pipeline_meta_path(slug: str, kind: WipOrPublished) -> str:
    """Per-reciter immutable extraction-time facts.

    Schema: ``scripts/lib/schemas/pipeline_meta.py::PipelineMeta``. Written
    once by extraction (or the backfill script for legacy reciters); read
    by ``services/storage/data_loader.load_pipeline_meta``. Immutable
    post-extraction — never invalidated by save.
    """
    return reciter_file(slug, kind, "pipeline_meta.json")


def published_timestamps_path(slug: str, chapter: str | int) -> str:
    """Timestamps live only under ``published/<slug>/timestamps/`` — not wip."""
    return f"published/{slug}/timestamps/{chapter}.json"


def prefetched_audio_dir(slug: str) -> str:
    return f"wip/{slug}/audio"


def prefetched_audio_path(slug: str, chapter: str | int) -> str:
    """MP3 written by the katana extraction pipeline for in-review reciters."""
    return f"wip/{slug}/audio/{chapter}.mp3"


def _peaks_root(slug: str) -> str:
    """Resolve the bucket root (``wip`` vs ``published``) for ``slug``.

    Reciter state determines which subtree owns the peaks file. Lazy import
    keeps this module free of the ``data_dir → storage_paths`` cycle
    (``data_dir`` imports us at module load).
    """
    from . import data_dir
    return data_dir.kind_for(slug)  # "wip" or "published"


def prefetched_peaks_dir(slug: str) -> str:
    return f"{_peaks_root(slug)}/{slug}/peaks"


def prefetched_peaks_path(slug: str, chapter: str | int) -> str:
    """Slim packed peaks (gzipped) paired with the prefetched audio.

    Schema v3 format produced by ``services/audio/peaks_slim.py::pack_slim``:
    int8-quantized, decimated to ``PEAKS_SLIM_BPS=10`` bps, JSON-wrapped,
    gzipped. Reader (``audio_fetch.read_prefetched_peaks``) inflates via
    ``unpack_slim`` so downstream consumers see a standard
    ``{duration_ms, peaks: list[list[float]]}`` dict.

    Path is state-aware: ``wip/<slug>/...`` for in-flight reciters,
    ``published/<slug>/...`` once they ship. No fallback — the kind lookup
    is single-source-of-truth (``data_dir.kind_for``).

    Pre-v3 files (``<chapter>.json``) are migrated to ``.json.gz`` by
    ``scripts/backfill_peaks_slim.py`` and originals are renamed to
    ``.json.bak`` for rollback.
    """
    return f"{_peaks_root(slug)}/{slug}/peaks/{chapter}.json.gz"


def prefetched_peaks_legacy_path(slug: str, chapter: str | int) -> str:
    """Pre-v3 path (``<chapter>.json``). Used only by the backfill + rollback
    scripts -- runtime reads go through ``prefetched_peaks_path`` (v3 .gz)."""
    return f"{_peaks_root(slug)}/{slug}/peaks/{chapter}.json"


def prefetched_peaks_backup_path(slug: str, chapter: str | int) -> str:
    """Backup name used during dev-bucket migration. Originals get renamed
    here so rollback can restore them. Cleaned up after prod cutover."""
    return f"{_peaks_root(slug)}/{slug}/peaks/{chapter}.json.bak"


def prefetch_done_marker_path(slug: str) -> str:
    """Sentinel written atomically last; presence ⇒ prefetch fully completed."""
    return f"wip/{slug}/audio/_done.json"


def intake_source_path(slug: str) -> str:
    """Normalised audio source stashed when an intake request is accepted.

    Written once by ``services.admin.intake.accept`` (the contributor's
    direct-links / playlist source for the freshly-minted delivery); consumed
    by the offline ingest pipeline. Schema: ``IntakeSource``."""
    return f"wip/{slug}/intake.json"


PER_RECITER_FILES: tuple[str, ...] = (
    "segments.json",
    "detailed.json",
    "edit_history.jsonl",
    "edit_history_peaks.jsonl",
    "low_confidence_v2.json",
    "auto_split_v1.json",
    "pipeline_meta.json",
)
