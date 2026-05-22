/**
 * Admin dashboard → Requests-tab API client.
 *
 * Backed by ``/api/admin/requests`` (maintainer+), ``/unviewed-count``
 * (maintainer+), and ``/<id>/view`` (maintainer+) — see
 * ``inspector/routes/claims/requests.py``. Reject actions (owner-only) live in
 * ``lib/api/requests.ts`` (keyed by slug).
 */

import type { AdminRequestsResponse, ProbeResponse } from '../types/generated/schemas';

export type RequestStatus = 'open' | 'accepted' | 'returned' | 'discarded';

const _JSON = { 'Content-Type': 'application/json' };

/** Owner-confirmed catalog fields for accepting an intake request. */
export interface AcceptIntakeFields {
    slug: string;
    reciter_id: string;
    source: string;
    channel: string;
}

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
        headers: _JSON,
    });
    if (!res.ok) throw new Error(`markRequestViewed: HTTP ${res.status}`);
}

// ---- Intake (slugless new-combo / new-reciter) owner actions ----------------

async function _post(url: string, body?: unknown): Promise<Record<string, unknown>> {
    const res = await fetch(url, {
        method: 'POST',
        headers: _JSON,
        body: body === undefined ? undefined : JSON.stringify(body),
    });
    const json = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    if (!res.ok) {
        throw new Error((json.error as string) ?? `HTTP ${res.status}`);
    }
    return json;
}

/** Mint the catalog entry + queue an intake request for alignment. */
export async function acceptRequest(id: string, fields: AcceptIntakeFields): Promise<string> {
    const json = await _post(`/api/admin/requests/${id}/accept`, fields);
    return json.slug as string;
}

/** Reachability-probe an intake request's audio source (owner-only). */
export async function probeRequest(id: string): Promise<ProbeResponse> {
    const json = await _post(`/api/admin/requests/${id}/probe`);
    return json as unknown as ProbeResponse;
}

/** Send an intake request back to the contributor (≥10-char reason). */
export async function returnRequest(id: string, reason: string): Promise<void> {
    await _post(`/api/admin/requests/${id}/return`, { reason });
}

/** Discard an intake request (≥10-char reason). */
export async function discardRequest(id: string, reason: string): Promise<void> {
    await _post(`/api/admin/requests/${id}/discard`, { reason });
}
