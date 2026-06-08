/**
 * Public activity feed fetcher.
 *
 * Backed by ``/api/public/activity`` which is itself backed by
 * ``services/public_activity.py`` — the six-event allowlist.
 */

export type PublicEventKind =
    | 'added'
    | 'requested'
    | 'available_for_review'
    | 'under_review'
    | 'published';

export interface PublicActivityCard {
    ts: string;
    kind: PublicEventKind;
    name: string;
    /** Delivery riwayah slug. `null` when the slug is no longer in the catalog. */
    riwayah: string | null;
    /** Delivery style slug. `null` when the slug is no longer in the catalog. */
    style: string | null;
    /** Fallback human-readable line; the frontend prefers composing from structured fields. */
    text: string;
    /** Stable id derived from the underlying audit record. Always present. */
    audit_id?: string;
    /** Populated only when the caller is signed in as an owner. */
    actor_login?: string;
    actor_hf_user_id?: string;
}

export interface PublicActivityPage {
    cards: PublicActivityCard[];
    next_cursor: number | null;
    total: number;
}

export interface FetchActivityOpts {
    cursor?: number;
    limit?: number;
    signal?: AbortSignal;
}

export async function fetchPublicActivity(
    opts: FetchActivityOpts = {},
): Promise<PublicActivityPage> {
    const params = new URLSearchParams();
    if (opts.cursor !== undefined) params.set('cursor', String(opts.cursor));
    if (opts.limit !== undefined) params.set('limit', String(opts.limit));
    const qs = params.toString();
    const url = `/api/public/activity${qs ? `?${qs}` : ''}`;
    const resp = await fetch(url, { signal: opts.signal });
    if (!resp.ok) {
        throw new Error(`fetchPublicActivity: HTTP ${resp.status}`);
    }
    return (await resp.json()) as PublicActivityPage;
}
