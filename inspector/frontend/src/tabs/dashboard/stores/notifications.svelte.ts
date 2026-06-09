/**
 * "My Notifications" rail store (Svelte 5 runes).
 *
 * Holds the signed-in user's active + archived notifications, the unread
 * badge count, and the rail's Active/Archive view toggle. Polls the active
 * list on a visibility-aware 30s cadence (matching the activity rail);
 * opening the active list server-side marks it seen, so the badge clears.
 *
 * Dismiss/restore are optimistic (move between active⇄archived immediately,
 * roll back on error) — mirroring the activity rail's delete affordance.
 */

import {
    dismissNotification,
    fetchArchivedNotifications,
    fetchNotifications,
    restoreNotification,
    type UserNotification,
} from '../../../lib/api/notifications';
import { visiblePoll } from '../../../lib/utils/visible-poll';

export type NotificationsView = 'active' | 'archive';

class NotificationsStore {
    active = $state<UserNotification[]>([]);
    archived = $state<UserNotification[]>([]);
    unread = $state(0);
    view = $state<NotificationsView>('active');
    loading = $state(true);
    error = $state<string | null>(null);
    archivedLoaded = $state(false);

    #teardown: (() => void) | null = null;

    /** Begin the visibility-aware poll of the active list. Idempotent. */
    start(): void {
        if (this.#teardown) return;
        this.#teardown = visiblePoll<{ notifications: UserNotification[]; unread: number }>({
            intervalMs: 30_000,
            fetcher: (signal) => fetchNotifications(signal),
            onResult: (page) => {
                this.active = page.notifications;
                this.unread = page.unread;
                this.loading = false;
                this.error = null;
            },
            onError: (e) => {
                this.loading = false;
                this.error = (e as Error).message ?? 'Failed to load notifications';
            },
        });
    }

    stop(): void {
        this.#teardown?.();
        this.#teardown = null;
    }

    setView(v: NotificationsView): void {
        this.view = v;
        if (v === 'archive' && !this.archivedLoaded) void this.loadArchived();
    }

    async loadArchived(): Promise<void> {
        try {
            const r = await fetchArchivedNotifications();
            this.archived = r.notifications;
            this.archivedLoaded = true;
        } catch (e) {
            this.error = (e as Error).message ?? 'Failed to load archive';
        }
    }

    /** Archive one active notification (optimistic; rolls back on error). */
    async dismiss(id: number): Promise<void> {
        const idx = this.active.findIndex((n) => n.id === id);
        if (idx === -1) return;
        const item = this.active[idx]!;
        this.active = [...this.active.slice(0, idx), ...this.active.slice(idx + 1)];
        try {
            await dismissNotification(id);
            if (this.archivedLoaded) {
                this.archived = [{ ...item, dismissed_at: new Date().toISOString() }, ...this.archived];
            }
        } catch (e) {
            this.active = [...this.active.slice(0, idx), item, ...this.active.slice(idx)];
            this.error = (e as Error).message ?? 'Failed to dismiss';
        }
    }

    /** Restore one archived notification back to active (optimistic). */
    async restore(id: number): Promise<void> {
        const idx = this.archived.findIndex((n) => n.id === id);
        if (idx === -1) return;
        const item = this.archived[idx]!;
        this.archived = [...this.archived.slice(0, idx), ...this.archived.slice(idx + 1)];
        try {
            await restoreNotification(id);
            this.active = [{ ...item, dismissed_at: null }, ...this.active];
        } catch (e) {
            this.archived = [...this.archived.slice(0, idx), item, ...this.archived.slice(idx)];
            this.error = (e as Error).message ?? 'Failed to restore';
        }
    }
}

export const notifications = new NotificationsStore();
