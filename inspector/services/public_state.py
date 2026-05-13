"""Public state mapper for the Phase 6 dashboard.

Translates the internal ``ReciterRow`` + catalog delivery + reciter into the
six-bucket public taxonomy and strips assignee identity from every payload.
Never reveals slugs in user-facing copy — the slug is included only as a
stable client-side ID for grouping / picker selection, never rendered to the
user. See ``inspector/CLAUDE.md`` for the slug-exposure rule.

The public surface aggregates by reciter (one row per ``reciter_id``) and
embeds the reciter's deliveries inline. The dashboard frontend renders one
reciter row + an inline-expandable deliveries sub-table, so backend doing
the aggregation keeps the UI thin and the data shape unambiguous.

Authoritative spec:
- Phase 6 contract: docs/planning/inspector-deploy/v2/phases/06-public-dashboard.md
- Public taxonomy + activity feed: §1, §"Public activity feed"

Slice B of phase 6.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from scripts.lib.schemas import (
    AudioCategory,
    Delivery,
    ReciterEntry,
    ReciterRow,
    ReciterState,
    Visibility,
)

from . import catalog as catalog_service
from . import state as state_service


PublicBucket = Literal[
    "available_for_request",
    "requested",
    "available_for_review",
    "under_review",
    "publishing",
    "published",
]

# Order matters — used to compute "primary_bucket" as the most-progressed
# bucket across a reciter's deliveries. Higher index = more progressed.
_BUCKET_PROGRESS: dict[PublicBucket, int] = {
    "available_for_request": 0,
    "requested": 1,
    "available_for_review": 2,
    "under_review": 3,
    "publishing": 4,
    "published": 5,
}

# Full-mushaf chapter counts per audio category. Anything less is "partial".
_FULL_CHAPTERS: dict[AudioCategory, int] = {
    AudioCategory.BY_SURAH: 114,
    AudioCategory.BY_AYAH: 6236,
}


# ---------- types (TypedDicts for docs; runtime returns plain dicts) ----------


class PublicDelivery(TypedDict, total=False):
    slug: str                    # ID only — never rendered to users.
    bucket: PublicBucket
    state_since: str | None      # ISO datetime; None when no state row exists.
    riwayah: str
    style: str
    recording_context: str | None
    recording_year: int | None
    source: str
    channel: str
    channel_name: str            # human display name from vocab; falls back to slug
    audio_category: str          # by_surah | by_ayah
    chapter_count: int
    coverage_kind: Literal["full", "partial"]
    bitrate_kbps_nominal: int | None
    bitrate_mode: str
    total_duration_sec: int | None


class PublicReciter(TypedDict, total=False):
    reciter_id: str              # ID only.
    name: str                    # display (en)
    name_ar: str | None
    country: str | None
    primary_bucket: PublicBucket
    buckets: list[PublicBucket]  # union across deliveries
    deliveries: list[PublicDelivery]
    riwayat: list[str]
    styles: list[str]
    recording_contexts: list[str]  # null entries dropped at the producer
    sources: list[str]
    channels: list[str]
    chapter_count_total: int
    deliveries_count: int
    coverage_kind: Literal["full", "partial", "mixed"]
    last_activity: str | None    # max state_since across deliveries


# ---------- core mappers ----------


def bucket_for(row: ReciterRow | None) -> PublicBucket:
    """Translate an internal state row to a public bucket.

    ``None`` means the catalog has a delivery but no state row has been
    created — that's ``available_for_request`` (a "suggest this reciter"
    affordance in the UI).
    """
    if row is None:
        return "available_for_request"

    state = row.state
    if state in (ReciterState.CATALOGUED, ReciterState.AWAITING_ALIGNMENT):
        return "requested"
    if state == ReciterState.AWAITING_REVIEW:
        return "available_for_review"
    if state == ReciterState.UNDER_REVIEW:
        return "publishing" if row.marked_ready else "under_review"
    if state == ReciterState.AWAITING_TIMESTAMPS:
        return "publishing"
    if state in (ReciterState.RELEASED, ReciterState.COMPLETED):
        return "published"

    # Defensive — should be unreachable; new ReciterState members must add
    # an explicit branch above (callers depend on the closed set).
    raise ValueError(f"unmapped reciter state: {state!r}")


def _delivery_coverage(d: Delivery) -> Literal["full", "partial"]:
    full = _FULL_CHAPTERS.get(d.audio_category)
    if full is None or d.chapter_count < full:
        return "partial"
    return "full"


def _to_public_delivery(
    d: Delivery,
    row: ReciterRow | None,
    channel_names: dict[str, str],
) -> PublicDelivery:
    return PublicDelivery(
        slug=d.slug,
        bucket=bucket_for(row),
        state_since=(row.state_since.isoformat() if row is not None else None),
        riwayah=d.riwayah,
        style=d.style,
        recording_context=d.recording_context,
        recording_year=d.recording_year,
        source=d.source,
        channel=d.channel,
        channel_name=channel_names.get(d.channel, d.channel),
        audio_category=d.audio_category.value,
        chapter_count=d.chapter_count,
        coverage_kind=_delivery_coverage(d),
        bitrate_kbps_nominal=d.bitrate_kbps_nominal,
        bitrate_mode=d.bitrate_mode.value if hasattr(d.bitrate_mode, "value") else str(d.bitrate_mode),
        total_duration_sec=d.total_duration_sec,
    )


def _primary_bucket(buckets: list[PublicBucket]) -> PublicBucket:
    if not buckets:
        return "available_for_request"
    return max(buckets, key=lambda b: _BUCKET_PROGRESS[b])


def _coverage_rollup(
    deliveries: list[PublicDelivery],
) -> Literal["full", "partial", "mixed"]:
    if not deliveries:
        return "partial"
    kinds = {d["coverage_kind"] for d in deliveries}
    if kinds == {"full"}:
        return "full"
    if kinds == {"partial"}:
        return "partial"
    return "mixed"


def _unique_ordered(values: list) -> list:
    """Order-preserving dedupe; preserves the first-seen order across deliveries."""
    seen = set()
    out = []
    for v in values:
        key = v  # hashable (strings, None)
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


def _channel_name_map() -> dict[str, str]:
    catalog = catalog_service.snapshot()
    return {ch.slug: ch.name for ch in catalog.vocab.channels}


def to_public_reciter(
    reciter: ReciterEntry,
    deliveries: list[Delivery],
    state_index: dict[str, ReciterRow],
    channel_names: dict[str, str] | None = None,
) -> PublicReciter:
    """Aggregate one reciter's catalog + state into a single public payload.

    ``state_index`` maps ``delivery_slug → ReciterRow`` and is built once at
    the call site so this fn stays O(deliveries). Deliveries whose slug isn't
    in ``state_index`` map to ``available_for_request``.

    Visibility: deliveries with ``visibility=discarded`` on their state row
    are excluded entirely (admin-only listing surfaces them via a separate
    code path in Phase 7).
    """
    if channel_names is None:
        channel_names = _channel_name_map()
    public_dels: list[PublicDelivery] = []
    for d in deliveries:
        row = state_index.get(d.slug)
        if row is not None and row.visibility != Visibility.PUBLIC:
            continue
        public_dels.append(_to_public_delivery(d, row, channel_names))

    buckets = _unique_ordered([d["bucket"] for d in public_dels])
    last_activity_values = [d["state_since"] for d in public_dels if d["state_since"]]
    last_activity = max(last_activity_values) if last_activity_values else None

    return PublicReciter(
        reciter_id=reciter.reciter_id,
        name=reciter.name_en,
        name_ar=reciter.name_ar,
        country=reciter.country,
        primary_bucket=_primary_bucket(buckets),
        buckets=buckets,
        deliveries=public_dels,
        riwayat=_unique_ordered([d["riwayah"] for d in public_dels]),
        styles=_unique_ordered([d["style"] for d in public_dels]),
        recording_contexts=_unique_ordered(
            [d["recording_context"] for d in public_dels if d["recording_context"]]
        ),
        sources=_unique_ordered([d["source"] for d in public_dels]),
        channels=_unique_ordered([d["channel"] for d in public_dels]),
        chapter_count_total=sum(d["chapter_count"] for d in public_dels),
        deliveries_count=len(public_dels),
        coverage_kind=_coverage_rollup(public_dels),
        last_activity=last_activity,
    )


# ---------- list / stats helpers ----------


def _build_state_index() -> dict[str, ReciterRow]:
    """Snapshot the in-memory state store into a slug-keyed index."""
    return {row.slug: row for row in state_service.all_rows()}


def all_public_reciters() -> list[PublicReciter]:
    """Materialize every catalog reciter as a public payload.

    A reciter with zero deliveries (theoretically possible at catalog-edit
    boundaries) is skipped — the dashboard has nothing to render for it.
    """
    catalog = catalog_service.snapshot()
    state_index = _build_state_index()
    channel_names = {ch.slug: ch.name for ch in catalog.vocab.channels}

    # Group deliveries by reciter_id once.
    by_reciter: dict[str, list[Delivery]] = {}
    for d in catalog.deliveries:
        by_reciter.setdefault(d.reciter_id, []).append(d)

    out: list[PublicReciter] = []
    for reciter in catalog.reciters:
        dels = by_reciter.get(reciter.reciter_id, [])
        if not dels:
            continue
        public = to_public_reciter(reciter, dels, state_index, channel_names)
        # If every delivery was discarded, the reciter has no public deliveries
        # — also skip; it would render an empty row.
        if not public["deliveries"]:
            continue
        out.append(public)
    return out


def detail(reciter_id: str) -> PublicReciter | None:
    """Materialize a single reciter for the public detail page.

    Returns ``None`` when the reciter_id isn't in the catalog, or when
    the reciter has no public deliveries (all discarded).
    """
    catalog = catalog_service.snapshot()
    reciter = next(
        (r for r in catalog.reciters if r.reciter_id == reciter_id), None,
    )
    if reciter is None:
        return None
    deliveries = [d for d in catalog.deliveries if d.reciter_id == reciter_id]
    if not deliveries:
        return None
    state_index = _build_state_index()
    channel_names = {ch.slug: ch.name for ch in catalog.vocab.channels}
    public = to_public_reciter(reciter, deliveries, state_index, channel_names)
    if not public["deliveries"]:
        return None
    return public


def stats() -> dict[str, int]:
    """Counts of reciters per public bucket — primary_bucket only.

    Buckets are mutually exclusive at the reciter level (each reciter has
    exactly one ``primary_bucket``), so the counts sum to the total number
    of public reciters.
    """
    counts: dict[str, int] = {b: 0 for b in _BUCKET_PROGRESS}
    for r in all_public_reciters():
        counts[r["primary_bucket"]] += 1
    return counts
