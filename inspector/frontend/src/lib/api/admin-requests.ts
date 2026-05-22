/**
 * Admin dashboard → Requests-tab API client.
 *
 * Backed by ``/api/admin/requests`` (maintainer+), ``/unviewed-count``
 * (maintainer+), and ``/<id>/view`` (maintainer+) — see
 * ``inspector/routes/claims/requests.py``. Reject actions (owner-only) live in
 * ``lib/api/requests.ts`` (keyed by slug).
 */

import type { AdminRequestsResponse } from '../types/generated/schemas';

export type RequestStatus = 'open' | 'accepted' | 'returned' | 'discarded';

export async function fetchRequests(
    status: RequestStatus,
    signal?: AbortSignal,
): Promise<AdminRequestsResponse> {
    const res = await fetch(`/api/admin/requests?status=${status}`, { signal });
    if (!res.ok) throw new Error(`fetchRequests: HTTP ${res.status}`);
    return (await res.json()) as AdminRequestsResponse;
}

export async function fetchUnviewedRequestCount(
    signal?: AbortSignal,
): Promise<number> {
    const res = await fetch('/api/admin/requests/unviewed-count', { signal });
    if (!res.ok) throw new Error(`unviewed-count: HTTP ${res.status}`);
    const body = (await res.json()) as { count?: number };
    return body.count ?? 0;
}

export async function markRequestViewed(id: string): Promise<void> {
    const res = await fetch(`/api/admin/requests/${id}/view`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) throw new Error(`markRequestViewed: HTTP ${res.status}`);
}
