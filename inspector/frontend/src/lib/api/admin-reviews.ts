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
    AdminReviewsResponse,
    AdminReviewValidation,
} from '../types/generated/schemas';

export async function fetchAdminReviews(signal?: AbortSignal): Promise<AdminReviewsResponse> {
    const resp = await fetch('/api/admin/reviews/list', { signal });
    if (!resp.ok) throw new Error(`fetchAdminReviews: HTTP ${resp.status}`);
    return (await resp.json()) as AdminReviewsResponse;
}

/** Marked-ready entries the calling admin hasn't viewed yet. Polled by the
 * admin entry-button dot; mirrors fetchUnviewedRequestCount. */
export async function fetchUnviewedReviewCount(signal?: AbortSignal): Promise<number> {
    const resp = await fetch('/api/admin/reviews/unviewed-count', { signal });
    if (!resp.ok) throw new Error(`unviewed-review-count: HTTP ${resp.status}`);
    const body = (await resp.json()) as { count?: number };
    return body.count ?? 0;
}

/** Advance the caller's ``viewed_at`` for ``slug`` (fires on first drawer
 * open). Best-effort — the FE optimistically drops the dot, the next list
 * fetch reconciles. */
export async function markReviewViewed(slug: string): Promise<void> {
    const resp = await fetch(`/api/admin/reviews/${encodeURIComponent(slug)}/view`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
    });
    if (!resp.ok) throw new Error(`markReviewViewed: HTTP ${resp.status}`);
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

async function postWithReason(path: string, reason: string): Promise<void> {
    const resp = await fetch(path, {
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

/**
 * Force-release the current open claim on ``slug``. Closes the claim and
 * transitions UNDER_REVIEW → AWAITING_REVIEW. Throws the server's ``error``
 * string verbatim on failure so the caller can surface it.
 */
export async function forceReleaseClaim(slug: string, reason: string): Promise<void> {
    return postWithReason(`/api/admin/claim/force-release/${encodeURIComponent(slug)}`, reason);
}

/**
 * Send a marked-ready recitation back to Under review. Fires
 * ``reciter.merge_rejected`` — keeps the claim open, clears ``marked_ready_at``.
 */
export async function sendBackToUnderReview(slug: string, reason: string): Promise<void> {
    return postWithReason(`/api/admin/send-back/${encodeURIComponent(slug)}`, reason);
}

// ---- Reviewer popover: lookup + reassign ----
//
// Both surfaces drive the owner-only "click the current reviewer → change or
// remove" popover in the General drawer. ``UserCard`` mirrors the response
// shape of ``/api/admin/users/lookup`` (and the ``to_user`` field of the
// reassign route). Not yet formalised in ``scripts/lib/schemas/`` — promote
// when a second surface starts consuming it.

export interface UserCard {
    hf_user_id: string;
    login: string;
    fullname: string | null;
    avatar_url: string | null;
}

/**
 * Resolve a free-text HF login → ``UserCard``. Returns ``null`` on 404
 * (unknown login — typo); throws with the server ``error`` string on 502
 * (transport failure) or any other non-200.
 */
export async function lookupUser(
    login: string,
    signal?: AbortSignal,
): Promise<UserCard | null> {
    const resp = await fetch('/api/admin/users/lookup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ login }),
        signal,
    });
    if (resp.status === 404) return null;
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
    return (await resp.json()) as UserCard;
}

/**
 * Reassign the open claim on ``slug`` to a different reviewer (owner-only).
 * Mirrors ``forceReleaseClaim`` shape — throws the server ``error`` string
 * verbatim on failure so the caller can surface it inline.
 */
export async function reassignClaim(
    slug: string,
    to_login: string,
    reason: string,
): Promise<void> {
    const resp = await fetch(
        `/api/admin/claim/reassign/${encodeURIComponent(slug)}`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ to_login, reason }),
        },
    );
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
