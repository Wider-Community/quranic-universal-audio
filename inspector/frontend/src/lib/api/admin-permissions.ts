/**
 * Admin Permissions-tab API client. Backed by ``/api/admin/permissions`` (GET
 * matrix) and ``/api/admin/permissions/<cap>/<tier>`` (POST toggle / reset).
 * Owner-only (the ``manage_permissions`` capability gates both). Wire shapes
 * are codegen'd in ``lib/types/generated/schemas.ts``.
 */

import type { AdminPermissionsResponse } from '../types/generated/schemas';

export type PermissionTier = 'anonymous' | 'contributor' | 'maintainer';

export async function fetchAdminPermissions(
    signal?: AbortSignal,
): Promise<AdminPermissionsResponse> {
    const resp = await fetch('/api/admin/permissions', { signal });
    if (!resp.ok) throw new Error(`fetchAdminPermissions: HTTP ${resp.status}`);
    return (await resp.json()) as AdminPermissionsResponse;
}

async function postGrant(
    capabilityId: string,
    tier: PermissionTier,
    body: Record<string, unknown>,
): Promise<void> {
    const resp = await fetch(
        `/api/admin/permissions/${encodeURIComponent(capabilityId)}/${encodeURIComponent(tier)}`,
        {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        },
    );
    if (!resp.ok) {
        let msg = `HTTP ${resp.status}`;
        try {
            const b = (await resp.json()) as { error?: string };
            if (b?.error) msg = b.error;
        } catch {
            /* non-JSON body — keep the status fallback */
        }
        throw new Error(msg);
    }
}

/** Set one capability×tier cell. Instant + audited server-side. */
export function setCapabilityGrant(
    capabilityId: string,
    tier: PermissionTier,
    allowed: boolean,
): Promise<void> {
    return postGrant(capabilityId, tier, { allowed });
}

/** Reset one capability×tier cell back to the registry default. */
export function resetCapabilityGrant(
    capabilityId: string,
    tier: PermissionTier,
): Promise<void> {
    return postGrant(capabilityId, tier, { reset: true });
}
