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
    | 'published';

/**
 * Admin-extended bucket. ``discarded`` is the orthogonal visibility flag,
 * not a state-machine state — it only appears on combos returned in the
 * ``discarded_deliveries`` array of ``/api/public/reciter/<id>`` when the
 * caller is a maintainer or owner. Used to type the StatePill rendered in
 * the admin-only discarded section of the reciter modal.
 */
export type AdminBucket = PublicBucket | 'discarded';

export const PUBLIC_BUCKET_LABELS: Record<AdminBucket, string> = {
    available_for_request: 'Available for request',
    requested: 'Requested',
    available_for_review: 'Available for review',
    under_review: 'Under review',
    published: 'Published',
    discarded: 'Discarded',
};

export const PUBLIC_BUCKETS: readonly PublicBucket[] = [
    'available_for_request',
    'requested',
    'available_for_review',
    'under_review',
    'published',
] as const;

/**
 * Status display ordering — most progressed first. Used for the dashboard
 * status filter cards, modal combination sort, and any UI that surfaces
 * lifecycle "rank". Distinct from `PUBLIC_BUCKETS` (ascending lifecycle).
 */
export const BUCKET_PRIORITY: readonly PublicBucket[] = [
    'published',
    'under_review',
    'available_for_review',
    'requested',
    'available_for_request',
] as const;

const BUCKET_RANK: Record<PublicBucket, number> = {
    published: 0,
    under_review: 1,
    available_for_review: 2,
    requested: 3,
    available_for_request: 4,
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

/**
 * Discarded delivery surface. Mirrors ``services.public_state.AdminViewDelivery``
 * — same fields as ``PublicDelivery`` plus ``visibility`` + ``visibility_reason``
 * so the modal can label why a combo was discarded.
 */
export interface AdminDiscardedDelivery extends PublicDelivery {
    visibility: 'public' | 'discarded';
    visibility_reason: string | null;
}

/**
 * Admin-view reciter payload. Returned by ``/api/public/reciter/<id>`` when
 * the caller is signed in as maintainer or owner. ``deliveries`` still
 * contains only public combos (same as the anonymous shape) so the existing
 * counts + sorts stay consistent; discarded combos move into a dedicated
 * array for the maintainer-only section of the modal.
 */
export interface AdminViewReciter extends PublicReciter {
    discarded_deliveries: AdminDiscardedDelivery[];
    fully_discarded: boolean;
}

export interface PublicReciterPage {
    reciters: PublicReciter[];
    total: number;
    next_cursor: number | null;
}

export type BucketCounts = Record<PublicBucket, number>;
