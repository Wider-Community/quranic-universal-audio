/**
 * Public-bucket display vocabulary — FE-only value-level helpers.
 *
 * The ``PublicBucket`` literal union, ``AdminBucket``, the label / priority /
 * rank tables, ``bucketRank`` and ``CoverageKind`` have no wire producer — they
 * encode FE display ordering + copy. ``PublicBucket`` is the single source of
 * truth for the bucket literals. The data-contract reciter/delivery/page shapes
 * are codegen'd and imported straight from ``./generated/schemas``.
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
