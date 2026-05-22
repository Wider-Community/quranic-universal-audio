/**
 * Admin Users-panel API client. Backed by ``/api/admin/users``,
 * ``/api/admin/users/<id>``, ``/api/admin/visitor-stats`` (maintainer/owner).
 * Wire shapes are codegen'd in ``lib/types/generated/schemas.ts``.
 */

import type {
    AdminUserDetail,
    AdminUsersResponse,
    AdminVisitorStats,
} from '../types/generated/schemas';

export async function fetchAdminUsers(signal?: AbortSignal): Promise<AdminUsersResponse> {
    const resp = await fetch('/api/admin/users', { signal });
    if (!resp.ok) throw new Error(`fetchAdminUsers: HTTP ${resp.status}`);
    return (await resp.json()) as AdminUsersResponse;
}

/** Returns null on 404 (unknown user), throws on other errors. */
export async function fetchAdminUser(
    hfUserId: string,
    signal?: AbortSignal,
): Promise<AdminUserDetail | null> {
    const resp = await fetch(`/api/admin/users/${encodeURIComponent(hfUserId)}`, { signal });
    if (resp.status === 404) return null;
    if (!resp.ok) throw new Error(`fetchAdminUser: HTTP ${resp.status}`);
    return (await resp.json()) as AdminUserDetail;
}

export async function fetchVisitorStats(signal?: AbortSignal): Promise<AdminVisitorStats> {
    const resp = await fetch('/api/admin/visitor-stats', { signal });
    if (!resp.ok) throw new Error(`fetchVisitorStats: HTTP ${resp.status}`);
    return (await resp.json()) as AdminVisitorStats;
}

/**
 * Owner-only role change. POSTs to ``/api/admin/users/<id>/role``. Throws with
 * the server's ``error`` string on failure (e.g. the 409 last-owner guard) so
 * the caller can surface it verbatim.
 */
export async function setUserRole(
    hfUserId: string,
    role: 'contributor' | 'maintainer' | 'owner',
    login?: string | null,
): Promise<void> {
    const resp = await fetch(`/api/admin/users/${encodeURIComponent(hfUserId)}/role`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role, login: login ?? undefined }),
    });
    if (!resp.ok) {
        let msg = `HTTP ${resp.status}`;
        try {
            const body = (await resp.json()) as { error?: string };
            if (body?.error) msg = body.error;
        } catch {
            /* non-JSON body — keep the status fallback */
        }
        throw new Error(msg);
    }
}
