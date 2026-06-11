/**
 * Announcements client.
 *
 * Public read (`GET /api/announcements`, anonymous-reachable — see
 * `inspector/routes/announcements.py`) drives the global announcement cards in
 * the "My Notifications" rail. Owner compose / revoke / management-list hit
 * `/api/admin/announcements` (gated on `announcements.send` — see
 * `inspector/routes/admin/announcements.py`).
 *
 * Dismiss/seen state is NOT server-side — the browser tracks it in localStorage
 * (see `tabs/dashboard/stores/announcements.svelte.ts`).
 */

import type { Announcement } from '../types/generated/schemas';

const _JSON = { 'Content-Type': 'application/json' };

/** Admin management shape: public fields + author + revoked_at. */
export interface AnnouncementAdmin extends Announcement {
    author_login: string | null;
    revoked_at: string | null;
}

/** Active announcements for the rail. Public — works signed-out. */
export async function fetchAnnouncements(signal?: AbortSignal): Promise<Announcement[]> {
    const res = await fetch('/api/announcements', { signal });
    if (!res.ok) throw new Error(`fetchAnnouncements: HTTP ${res.status}`);
    const body = (await res.json()) as { announcements: Announcement[] };
    return body.announcements;
}

/** Active + revoked announcements for the admin management tab. */
export async function listAnnouncements(signal?: AbortSignal): Promise<AnnouncementAdmin[]> {
    const res = await fetch('/api/admin/announcements', { signal });
    if (!res.ok) throw new Error(`listAnnouncements: HTTP ${res.status}`);
    const body = (await res.json()) as { announcements: AnnouncementAdmin[] };
    return body.announcements;
}

/** Compose + broadcast one announcement. Returns the stored row. */
export async function createAnnouncement(
    title: string,
    body: string | null,
): Promise<AnnouncementAdmin> {
    const res = await fetch('/api/admin/announcements', {
        method: 'POST',
        headers: _JSON,
        body: JSON.stringify({ title, body }),
    });
    const json = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    if (!res.ok) throw new Error((json.error as string) ?? `HTTP ${res.status}`);
    return json as unknown as AnnouncementAdmin;
}

/** Revoke one announcement (hides it from every rail). */
export async function revokeAnnouncement(id: number): Promise<void> {
    const res = await fetch(`/api/admin/announcements/${id}/revoke`, {
        method: 'POST',
        headers: _JSON,
    });
    if (!res.ok) throw new Error(`revokeAnnouncement: HTTP ${res.status}`);
}
