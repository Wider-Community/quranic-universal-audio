/**
 * Per-user "My Notifications" client.
 *
 * Backed by ``/api/me/notifications`` (see
 * ``inspector/routes/auth/notifications.py``). Notifications are materialized
 * server-side by ``services/notifications`` for events that happened to the
 * signed-in user (request sent back / discarded, reciter ready, assigned,
 * claim force-released, segment-flag reply). Per-user, dismissable → archived.
 */

export interface UserNotification {
    id: number;
    /** Source event name, e.g. ``reciter.request_rejected_soft`` or ``flag.reply``. */
    event: string;
    /** Delivery slug to link to; ``null`` for slugless intake notifications. */
    slug: string | null;
    /** Frozen collapsed-view summary (always names the reciter). */
    title: string;
    /** Frozen expanded detail (admin reason / reply text); may be null. */
    body: string | null;
    created_at: string;
    seen_at: string | null;
    dismissed_at: string | null;
}

export interface NotificationsPage {
    notifications: UserNotification[];
    unread: number;
}

export async function fetchNotifications(
    signal?: AbortSignal,
): Promise<NotificationsPage> {
    const resp = await fetch('/api/me/notifications', { signal });
    if (!resp.ok) throw new Error(`fetchNotifications: HTTP ${resp.status}`);
    return (await resp.json()) as NotificationsPage;
}

export async function fetchArchivedNotifications(
    signal?: AbortSignal,
): Promise<{ notifications: UserNotification[] }> {
    const resp = await fetch('/api/me/notifications/archived', { signal });
    if (!resp.ok) throw new Error(`fetchArchivedNotifications: HTTP ${resp.status}`);
    return (await resp.json()) as { notifications: UserNotification[] };
}

export async function dismissNotification(id: number): Promise<void> {
    const resp = await fetch(`/api/me/notifications/${id}/dismiss`, { method: 'POST' });
    if (!resp.ok) throw new Error(`dismissNotification: HTTP ${resp.status}`);
}

export async function restoreNotification(id: number): Promise<void> {
    const resp = await fetch(`/api/me/notifications/${id}/restore`, { method: 'POST' });
    if (!resp.ok) throw new Error(`restoreNotification: HTTP ${resp.status}`);
}
