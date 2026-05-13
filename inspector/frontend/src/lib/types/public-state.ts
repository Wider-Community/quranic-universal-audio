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

export const PUBLIC_BUCKET_LABELS: Record<PublicBucket, string> = {
    available_for_request: 'Available for request',
    requested: 'Requested',
    available_for_review: 'Available for review',
    under_review: 'Under review',
    publishing: 'Publishing',
    published: 'Published',
};

export const PUBLIC_BUCKETS: readonly PublicBucket[] = [
    'available_for_request',
    'requested',
    'available_for_review',
    'under_review',
    'publishing',
    'published',
] as const;

/**
 * Status display ordering — most progressed first. Used for the dashboard
 * status filter cards, modal combination sort, and any UI that surfaces
 * lifecycle "rank". Distinct from `PUBLIC_BUCKETS` (ascending lifecycle).
 */
export const BUCKET_PRIORITY: readonly PublicBucket[] = [
    'published',
    'publishing',
    'under_review',
    'available_for_review',
    'requested',
    'available_for_request',
] as const;

const BUCKET_RANK: Record<PublicBucket, number> = {
    published: 0,
    publishing: 1,
    under_review: 2,
    available_for_review: 3,
    requested: 4,
    available_for_request: 5,
};

export function bucketRank(b: PublicBucket): number {
    return BUCKET_RANK[b];
}

export type CoverageKind = 'full' | 'partial' | 'mixed';

export interface PublicDelivery {
    slug: string;                       // internal-only; never rendered to users
    riwayah: string;
    style: string;
    recording_context: string | null;
    recording_year: number | null;
    source: string;
    channel: string;
    channel_name: string;
    audio_category: string;
    chapter_count: number;
    coverage_kind: 'full' | 'partial';
    state_since: string | null;
    bitrate_kbps_nominal: number | null;
    bitrate_mode: string; // cbr | vbr | abr | mixed | unknown
    total_duration_sec: number | null;
    bucket: PublicBucket;
}

export interface PublicReciter {
    reciter_id: string;                 // internal lookup key; never rendered
    name: string;
    name_ar: string | null;
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
