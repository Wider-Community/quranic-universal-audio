/**
 * Request-flow API client — user submit + admin review/reject + undiscard.
 *
 * Backed by ``/api/reciter/<slug>/request`` (contributor+),
 * ``/api/admin/request/<slug>/...`` (maintainer+), and
 * ``/api/admin/reciter/<slug>/undiscard`` (owner-only) —
 * see ``inspector/routes/requests.py``.
 */

export interface ProposedEdits {
    riwayah?: string | null;
    style?: string | null;
    name_en?: string | null;
    name_ar?: string | null;
    country?: string | null;
    recording_context?: string | null;
    recording_year?: number | null;
}

export interface SubmitRequestPayload {
    proposed_edits: ProposedEdits;
    comments: string | null;
    auto_claim: boolean;
}

export interface PendingRequest {
    slug: string;
    submitted_at: string;
    proposed_edits: ProposedEdits;
    comments: string | null;
    auto_claim: boolean;
    /** Present only for owner callers. */
    requester_login?: string;
    requester_hf_user_id?: string;
    requester_role: 'contributor' | 'maintainer' | 'owner';
}

async function _postJson(
    url: string,
    body: Record<string, unknown>,
): Promise<unknown> {
    const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!resp.ok) {
        const text = await resp.text();
        throw new Error(
            `POST ${url} → HTTP ${resp.status}: ${text.slice(0, 200)}`,
        );
    }
    return resp.json();
}

/**
 * Submit a new request. Returns the new state ("awaiting_alignment") on
 * success. Resolves with an Error containing a 409 message when a pending
 * request already exists for this slug — caller surfaces that to the user.
 */
export async function submitRequest(
    slug: string,
    proposed_edits: ProposedEdits,
    comments: string | null,
    auto_claim: boolean = false,
): Promise<{ ok: true; slug: string; state: string }> {
    return _postJson(`/api/reciter/${slug}/request`, {
        proposed_edits,
        comments,
        auto_claim,
    }) as Promise<{ ok: true; slug: string; state: string }>;
}

export async function fetchPendingRequest(
    slug: string,
    opts: { signal?: AbortSignal } = {},
): Promise<PendingRequest | null> {
    const resp = await fetch(`/api/admin/request/${slug}`, { signal: opts.signal });
    if (resp.status === 404) return null;
    if (!resp.ok) {
        throw new Error(`fetchPendingRequest: HTTP ${resp.status}`);
    }
    return (await resp.json()) as PendingRequest;
}

export async function rejectRequestSoft(
    slug: string,
    reason: string,
): Promise<void> {
    await _postJson(`/api/admin/request/${slug}/reject-soft`, { reason });
}

export async function rejectRequestHard(
    slug: string,
    reason: string,
): Promise<void> {
    await _postJson(`/api/admin/request/${slug}/reject-hard`, { reason });
}

export async function undiscardReciter(
    slug: string,
    reason: string,
): Promise<void> {
    await _postJson(`/api/admin/reciter/${slug}/undiscard`, { reason });
}
