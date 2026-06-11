/**
 * Global announcements store (Svelte 5 runes).
 *
 * Holds the active announcements shown in the "My Notifications" rail. Unlike
 * the per-user notifications store, this is identity-free — it polls the public
 * `GET /api/announcements` so it works for signed-out visitors too. Dismiss and
 * seen state live entirely in localStorage (no server round-trip).
 *
 * Seen model: a localStorage id-set records every announcement the browser has
 * already shown. `unread` / unseen-styling compare against a snapshot of that
 * set taken at page load, so a freshly-arrived announcement reads as "new" for
 * the whole session (the always-visible rail doesn't clear it instantly), while
 * a later visit — when the id is already persisted — shows it as read.
 *
 * Polls on the same visibility-aware 30s cadence as the notifications + activity
 * rails.
 */

import { fetchAnnouncements } from '../../../lib/api/announcements';
import type { Announcement } from '../../../lib/types/generated/schemas';
import { LS_KEYS } from '../../../lib/utils/constants';
import { visiblePoll } from '../../../lib/utils/visible-poll';

function loadIdSet(key: string): Set<number> {
    try {
        const raw = localStorage.getItem(key);
        if (!raw) return new Set();
        const arr = JSON.parse(raw) as unknown;
        if (Array.isArray(arr)) return new Set(arr.filter((n): n is number => typeof n === 'number'));
    } catch {
        /* storage unavailable / malformed — start empty */
    }
    return new Set();
}

function saveIdSet(key: string, set: Set<number>): void {
    try {
        localStorage.setItem(key, JSON.stringify([...set]));
    } catch {
        /* best-effort */
    }
}

class AnnouncementsStore {
    /** Active server announcements minus locally-dismissed ones, newest-first. */
    active = $state<Announcement[]>([]);
    /** Announcements new since the last visit (not in the page-load seen snapshot). */
    unread = $derived(this.active.filter((a) => !this.#seenAtLoad.has(a.id)).length);

    #dismissed = loadIdSet(LS_KEYS.DISMISSED_ANNOUNCEMENTS);
    /** Snapshot of the seen-set at page load — drives "new" styling for this session. */
    #seenAtLoad = loadIdSet(LS_KEYS.SEEN_ANNOUNCEMENTS);
    #teardown: (() => void) | null = null;

    /** Begin the visibility-aware poll of the active list. Idempotent. */
    start(): void {
        if (this.#teardown) return;
        this.#teardown = visiblePoll<Announcement[]>({
            intervalMs: 30_000,
            fetcher: (signal) => fetchAnnouncements(signal),
            onResult: (rows) => {
                this.active = rows.filter((a) => !this.#dismissed.has(a.id));
                this.#persistSeen();
            },
            onError: () => {
                /* announcements are non-critical — keep the last good list */
            },
        });
    }

    stop(): void {
        this.#teardown?.();
        this.#teardown = null;
    }

    /** Permanently hide one announcement on this browser. */
    dismiss(id: number): void {
        this.#dismissed.add(id);
        saveIdSet(LS_KEYS.DISMISSED_ANNOUNCEMENTS, this.#dismissed);
        this.active = this.active.filter((a) => a.id !== id);
    }

    /** Has this announcement been seen in a PRIOR visit? (drives unseen styling) */
    isNew(id: number): boolean {
        return !this.#seenAtLoad.has(id);
    }

    /** Record every currently-active id as seen for the NEXT visit (storage only;
     * the page-load snapshot is untouched so this session's "new" flags persist). */
    #persistSeen(): void {
        const persisted = loadIdSet(LS_KEYS.SEEN_ANNOUNCEMENTS);
        let changed = false;
        for (const a of this.active) {
            if (!persisted.has(a.id)) {
                persisted.add(a.id);
                changed = true;
            }
        }
        if (changed) saveIdSet(LS_KEYS.SEEN_ANNOUNCEMENTS, persisted);
    }
}

export const announcements = new AnnouncementsStore();
