/**
 * Dev-mode role switcher client.
 *
 * Backed by `POST /api/dev/role`, which is only registered when the Flask
 * server is running with `INSPECTOR_DEV_MODE=1`. On the deployed HF Space
 * the endpoint 404s and this module is never reached because the UI hides
 * the switcher (gated on `$currentUser.dev_mode`).
 */

import { fetchJson } from '../api';
import { loadCurrentUser } from '../stores/current-user';

export type DevRole = 'owner' | 'maintainer' | 'contributor' | 'anonymous';

export const DEV_ROLES: readonly DevRole[] = [
    'owner',
    'maintainer',
    'contributor',
    'anonymous',
] as const;

interface DevRoleResponse {
    ok?: boolean;
    role?: DevRole;
    error?: string;
}

/** Flip the synthetic-user role; re-hydrates `currentUser` on success. */
export async function setDevRole(role: DevRole): Promise<void> {
    const res = await fetchJson<DevRoleResponse>('/api/dev/role', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role }),
    });
    if (res?.error) {
        throw new Error(`dev role switch failed: ${res.error}`);
    }
    await loadCurrentUser();
}
