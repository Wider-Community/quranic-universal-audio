/**
 * Public-state types — mirror of ``inspector/services/public_state.py``.
 *
 * The wire shape from ``/api/public/*`` endpoints. Frontend never sees
 * assignee identity or internal state machine names; this module is the
 * single source of truth for ``PublicBucket`` literals.
 *
 * Slice B (backend) and Slice D (frontend primitives) of phase 6.
 */

export type PublicBucket =
    | 'available_for_request'
    | 'requested'
    | 'available_for_review'
    | 'under_review'
    | 'publishing'
    | 'published';

export const PUBLIC_BUCKETS: readonly PublicBucket[] = [
    'available_for_request',
    'requested',
    'available_for_review',
    'under_review',
    'publishing',
    'published',
] as const;

export type CoverageKind = 'full' | 'partial' | 'mixed';

export interface PublicDelivery {
    slug: string;                       // internal-only; never rendered to users
    riwayah: string;
    style: string;
    recording_context: string | null;
    recording_year: number | null;
    source: string;
    channel: string;
    audio_category: string;
    chapter_count: number;
    bucket: PublicBucket;
}

export interface PublicReciter {
    name: string;
    country: string | null;
    primary_bucket: PublicBucket;
    buckets: PublicBucket[];
    deliveries: PublicDelivery[];
    riwayat: string[];
    styles: string[];
    recording_contexts: string[];
    sources: string[];
    channels: string[];
    deliveries_count: number;
    chapter_count_total: number;
    coverage_kind: CoverageKind;
    last_activity: string | null;
}

export interface PublicReciterPage {
    reciters: PublicReciter[];
    total: number;
    next_cursor: number | null;
}

export type BucketCounts = Record<PublicBucket, number>;
