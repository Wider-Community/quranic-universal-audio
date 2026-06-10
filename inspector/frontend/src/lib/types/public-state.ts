/**
 * Public-state types — the wire shape from ``/api/public/*`` endpoints.
 *
 * The data-contract interfaces (``PublicReciter`` / ``PublicDelivery`` /
 * ``PublicReciterPage`` / ``AdminViewReciter`` / ``AdminDiscardedDelivery`` /
 * ``BucketCounts``) are RE-EXPORT SHIMS over the codegen'd wire types in
 * ``./generated/schemas`` (source of truth — never hand-edit those).
 *
 * The ``PublicBucket`` literal union, ``AdminBucket``, the label / priority /
 * rank tables, ``bucketRank`` and ``CoverageKind`` are FE-only value-level
 * helpers (no wire producer — they encode FE display ordering + copy) and stay
 * real definitions. ``PublicBucket`` remains the single source of truth for the
 * bucket literals.
 */

import type {
    AdminDiscardedDelivery as GenAdminDiscardedDelivery,
    AdminViewReciter as GenAdminViewReciter,
    BucketCounts as GenBucketCounts,
    PublicDelivery as GenPublicDelivery,
    PublicReciter as GenPublicReciter,
    PublicReciterPage as GenPublicReciterPage,
} from './generated/schemas';

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

/** One reciter delivery (riwayah × style × source × channel combo). Re-export
 *  shim over the generated wire type. */
export type PublicDelivery = GenPublicDelivery;

/** One reciter aggregated for the public dashboard. Re-export shim. */
export type PublicReciter = GenPublicReciter;

/**
 * Discarded delivery surface. Re-export shim over the generated wire type
 * (``PublicDelivery`` fields plus ``visibility`` + ``visibility_reason``).
 */
export type AdminDiscardedDelivery = GenAdminDiscardedDelivery;

/**
 * Admin-view reciter payload (maintainer / owner shape of
 * ``/api/public/reciter/<id>``). Re-export shim.
 */
export type AdminViewReciter = GenAdminViewReciter;

/** Paginated envelope of ``GET /api/public/reciters``. Re-export shim. */
export type PublicReciterPage = GenPublicReciterPage;

/** Per-bucket reciter tally of ``GET /api/public/stats``. Re-export shim
 *  (generated form is an open ``{ [k: string]: number }`` map). */
export type BucketCounts = GenBucketCounts;
