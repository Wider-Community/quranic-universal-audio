/**
 * Admin/owner activity-rail API client.
 *
 * Backed by ``/api/admin/activity`` (maintainer+) and
 * ``/api/public/activity/<audit_id>`` DELETE (owner-only) — see
 * ``inspector/routes/admin_activity.py``.
 */

export type AdminEventKind =
    | 'released'
    | 'marked_ready'
    | 'unmarked_ready'
    | 'merge_rejected'
    | 'unpublished'
    | 'dataset_published'
    | 'removed_from_dataset'
    | 'discarded'
    | 'undiscarded'
    | 'force_released'
    | 'reassigned'
    | 'force_set_state'
    | 'unlocked_for_revision';

export interface AdminActivityCard {
    audit_id: string;
    ts: string;
    kind: AdminEventKind;
    name: string;
    riwayah: string | null;
    style: string | null;
    text: string;
    /** Present only for owner callers — maintainers see redacted cards. */
    actor_login?: string;
    actor_hf_user_id?: string;
}

export interface AdminActivityPage {
    cards: AdminActivityCard[];
    /** Count of cards in the *other* bucket (archive when viewing live, vice versa). */
    archived_count: number;
    next_cursor: number | null;
    total: number;
}

export interface FetchAdminActivityOpts {
    cursor?: number;
    limit?: number;
    archived?: boolean;
    signal?: AbortSignal;
}

export async function fetchAdminActivity(
    opts: FetchAdminActivityOpts = {},
): Promise<AdminActivityPage> {
    const params = new URLSearchParams();
    if (opts.cursor !== undefined) params.set('cursor', String(opts.cursor));
    if (opts.limit !== undefined) params.set('limit', String(opts.limit));
    if (opts.archived) params.set('archived', 'true');
    const qs = params.toString();
    const url = `/api/admin/activity${qs ? `?${qs}` : ''}`;
    const resp = await fetch(url, { signal: opts.signal });
    if (!resp.ok) {
        throw new Error(`fetchAdminActivity: HTTP ${resp.status}`);
    }
    return (await resp.json()) as AdminActivityPage;
}

async function _postJson(url: string, body: Record<string, unknown>): Promise<void> {
    const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`POST ${url} → HTTP ${resp.status}: ${text.slice(0, 200)}`);
    }
}

export async function dismissAdminActivity(auditId: string): Promise<void> {
    await _postJson('/api/admin/activity/dismiss', { audit_id: auditId });
}

export async function undismissAdminActivity(auditId: string): Promise<void> {
    await _postJson('/api/admin/activity/undismiss', { audit_id: auditId });
}

export async function deletePublicActivity(
    auditId: string,
    reason: string,
): Promise<void> {
    const resp = await fetch(`/api/public/activity/${auditId}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
    });
    if (!resp.ok) {
        const text = await resp.text();
        throw new Error(
            `DELETE /api/public/activity/${auditId} → HTTP ${resp.status}: ` +
                text.slice(0, 200),
        );
    }
}
