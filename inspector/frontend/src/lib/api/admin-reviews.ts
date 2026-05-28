/**
 * Admin Reviews-tab API client. Backed by ``/api/admin/reviews/list``
 * (maintainer/owner). Wire shapes are codegen'd in
 * ``lib/types/generated/schemas.ts``.
 */

import type { AdminReviewsResponse } from '../types/generated/schemas';

export async function fetchAdminReviews(signal?: AbortSignal): Promise<AdminReviewsResponse> {
    const resp = await fetch('/api/admin/reviews/list', { signal });
    if (!resp.ok) throw new Error(`fetchAdminReviews: HTTP ${resp.status}`);
    return (await resp.json()) as AdminReviewsResponse;
}
