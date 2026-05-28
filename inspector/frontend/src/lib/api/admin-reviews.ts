/**
 * Admin Reviews-tab API client (maintainer/owner). Wire shapes are codegen'd
 * in ``lib/types/generated/schemas.ts``.
 *
 * - fetchAdminReviews             list across the four buckets
 * - fetchAdminReviewDetail        per-slug payload for the General drawer
 * - fetchAdminReviewValidation    lazy category counts (expands accordion)
 * - forceReleaseClaim             remove the current reviewer's open claim
 */

import type {
    AdminReviewDetail,
    AdminReviewValidation,
    AdminReviewsResponse,
} from '../types/generated/schemas';

export async function fetchAdminReviews(signal?: AbortSignal): Promise<AdminReviewsResponse> {
    const resp = await fetch('/api/admin/reviews/list', { signal });
    if (!resp.ok) throw new Error(`fetchAdminReviews: HTTP ${resp.status}`);
    return (await resp.json()) as AdminReviewsResponse;
}

/** Returns null on 404 (unknown slug), throws on other errors. */
export async function fetchAdminReviewDetail(
    slug: string,
    signal?: AbortSignal,
): Promise<AdminReviewDetail | null> {
    const resp = await fetch(`/api/admin/reviews/${encodeURIComponent(slug)}`, { signal });
    if (resp.status === 404) return null;
    if (!resp.ok) throw new Error(`fetchAdminReviewDetail: HTTP ${resp.status}`);
    return (await resp.json()) as AdminReviewDetail;
}

export async function fetchAdminReviewValidation(
    slug: string,
    signal?: AbortSignal,
): Promise<AdminReviewValidation> {
    const resp = await fetch(
        `/api/admin/reviews/${encodeURIComponent(slug)}/validation`,
        { signal },
    );
    if (!resp.ok) throw new Error(`fetchAdminReviewValidation: HTTP ${resp.status}`);
    return (await resp.json()) as AdminReviewValidation;
}

/**
 * Force-release the current open claim on ``slug``. Throws the server's
 * ``error`` string on failure so the caller can surface it verbatim.
 */
export async function forceReleaseClaim(slug: string, reason: string): Promise<void> {
    const resp = await fetch(`/api/admin/claim/force-release/${encodeURIComponent(slug)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
    });
    if (!resp.ok) {
        let msg = `HTTP ${resp.status}`;
        try {
            const body = (await resp.json()) as { error?: string };
            if (body?.error) msg = body.error;
        } catch {
            /* non-JSON body — keep status fallback */
        }
        throw new Error(msg);
    }
}
