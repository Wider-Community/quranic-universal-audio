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

# Single top-level prefix for ALL per-reciter content. Lifecycle state lives in
# the DB (the source of truth) — content location is state-independent, so a
# transition is a pure DB write and never moves files. Replaces the old
# state-driven ``wip/`` + ``published/`` split (see data-migrations.md).
RECITERS_PREFIX = "reciters"


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
    """Legacy bucket sidecar — global tombstones for the public activity rail
    (consumed by the one-shot JSON→SQLite migrator only; live writes go to
    the ``activity_tombstones`` table)."""
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


def reciter_dir(slug: str) -> str:
    return f"{RECITERS_PREFIX}/{slug}"


def reciter_file(slug: str, name: str) -> str:
    return f"{RECITERS_PREFIX}/{slug}/{name}"


def segments_path(slug: str) -> str:
    return reciter_file(slug, "segments.json")


def detailed_path(slug: str) -> str:
    return reciter_file(slug, "detailed.json")


def edit_history_path(slug: str) -> str:
    return reciter_file(slug, "edit_history.jsonl")


def edit_history_peaks_path(slug: str) -> str:
    return reciter_file(slug, "edit_history_peaks.jsonl")


def low_confidence_path(slug: str) -> str:
    return reciter_file(slug, "low_confidence_v2.json")


def auto_split_path(slug: str) -> str:
    """Auto-split cursor sidecar — per-seg precomputed cursors + refs.

    Written offline by ``scripts/lib/auto_split_precompute.py`` once segments
    are finalised; read at boot by ``services/data_loader.load_auto_split``.
    Replaces the runtime MFA Space call the inspector used to make on every
    Auto Split button click.
    """
    return reciter_file(slug, "auto_split_v1.json")


def pipeline_meta_path(slug: str) -> str:
    """Per-reciter immutable extraction-time facts.

    Schema: ``scripts/lib/schemas/pipeline_meta.py::PipelineMeta``. Written
    once by extraction (or the backfill script for legacy reciters); read
    by ``services/storage/data_loader.load_pipeline_meta``. Immutable
    post-extraction — never invalidated by save.
    """
    return reciter_file(slug, "pipeline_meta.json")


def timestamps_path(slug: str, chapter: str | int) -> str:
    """Per-chapter timestamps shard (legacy uncompressed). Only released
    reciters have these — the Timestamps tab gates on DB state, not file
    presence."""
    return reciter_file(slug, f"timestamps/{chapter}.json")


def timestamps_path_gz(slug: str, chapter: str | int) -> str:
    """Gzipped per-chapter v2 shard. The job writes these; the read-path
    prefers them and inflates, falling back to ``timestamps/<chapter>.json``
    for pre-v2 released reciters."""
    return reciter_file(slug, f"timestamps/{chapter}.json.gz")


def prefetched_audio_dir(slug: str) -> str:
    return reciter_file(slug, "audio")


def prefetched_audio_path(slug: str, chapter: str | int) -> str:
    """MP3 written by the katana extraction pipeline for in-review reciters."""
    return reciter_file(slug, f"audio/{chapter}.mp3")


def prefetched_peaks_dir(slug: str) -> str:
    return reciter_file(slug, "peaks")


def prefetched_peaks_path(slug: str, chapter: str | int) -> str:
    """Slim packed peaks (gzipped) paired with the prefetched audio.

    Schema v3 format produced by ``services/audio/peaks_slim.py::pack_slim``:
    int8-quantized, decimated to ``PEAKS_SLIM_BPS=10`` bps, JSON-wrapped,
    gzipped. Reader (``audio_fetch.read_prefetched_peaks``) inflates via
    ``unpack_slim`` so downstream consumers see a standard
    ``{duration_ms, peaks: list[list[float]]}`` dict.

    Pre-v3 files (``<chapter>.json``) are migrated to ``.json.gz`` by
    ``scripts/backfill_peaks_slim.py`` and originals are renamed to
    ``.json.bak`` for rollback.
    """
    return reciter_file(slug, f"peaks/{chapter}.json.gz")


def prefetched_peaks_legacy_path(slug: str, chapter: str | int) -> str:
    """Pre-v3 path (``<chapter>.json``). Used only by the backfill + rollback
    scripts -- runtime reads go through ``prefetched_peaks_path`` (v3 .gz)."""
    return reciter_file(slug, f"peaks/{chapter}.json")


def prefetched_peaks_backup_path(slug: str, chapter: str | int) -> str:
    """Backup name used during dev-bucket migration. Originals get renamed
    here so rollback can restore them. Cleaned up after prod cutover."""
    return reciter_file(slug, f"peaks/{chapter}.json.bak")


def prefetch_done_marker_path(slug: str) -> str:
    """Sentinel written atomically last; presence ⇒ prefetch fully completed."""
    return reciter_file(slug, "audio/_done.json")


PER_RECITER_FILES: tuple[str, ...] = (
    "segments.json",
    "detailed.json",
    "edit_history.jsonl",
    "edit_history_peaks.jsonl",
    "low_confidence_v2.json",
    "auto_split_v1.json",
    "pipeline_meta.json",
)
