/**
 * Bookmarks store — app-local by default, QF-synced when connected.
 *
 * Two modes:
 *  - Local (default): bookmarks live in localStorage (`insp_bookmarks`), seeded
 *    with a few example verses so the UX is demoable without a Quran.Foundation
 *    login.
 *  - Connected: when `/api/qf/status` reports a `qf_session`, the list hydrates
 *    from `/api/bookmarks` and mutations write through to the backend proxy.
 *
 * A bookmark is just a verse reference; the Timestamps tab adds the
 * random-reciter + word-level-timing layer on top when one is opened.
 */

import { get, writable } from 'svelte/store';

import {
    addRemoteBookmark,
    getQfStatus,
    getRemoteBookmarks,
    qfLogout,
    removeRemoteBookmark,
} from '../api/bookmarks-client';

export interface Bookmark {
    surah: number;
    ayah: number;
    key: string;
    addedAt: number;
}

const LS_KEY = 'insp_bookmarks';

const SEED: Array<[number, number]> = [
    [1, 1],
    [2, 255],
    [36, 1],
];

export const bookmarks = writable<Bookmark[]>([]);
export const bookmarksVisible = writable<boolean>(false);
export const qfConnected = writable<boolean>(false);
export const qfLogin = writable<string | null>(null);

export function bookmarkKey(surah: number, ayah: number): string {
    return `${surah}:${ayah}`;
}

export function isBookmarked(list: Bookmark[], key: string): boolean {
    return list.some((b) => b.key === key);
}

function makeBookmark(surah: number, ayah: number): Bookmark {
    return { surah, ayah, key: bookmarkKey(surah, ayah), addedAt: Date.now() };
}

function persistLocal(list: Bookmark[]): void {
    try {
        localStorage.setItem(LS_KEY, JSON.stringify(list));
    } catch {
        /* storage full / unavailable — local mode degrades to in-memory */
    }
}

function loadLocal(): Bookmark[] {
    try {
        const raw = localStorage.getItem(LS_KEY);
        if (raw === null) {
            const seeded = SEED.map(([s, a]) => makeBookmark(s, a));
            persistLocal(seeded);
            return seeded;
        }
        const parsed = JSON.parse(raw) as Bookmark[];
        if (Array.isArray(parsed)) return parsed;
    } catch {
        /* corrupt payload — fall through to empty */
    }
    return [];
}

/** Initialize on app mount: load local, then check QF connection + hydrate. */
export async function initBookmarks(): Promise<void> {
    bookmarks.set(loadLocal());
    try {
        const status = await getQfStatus();
        qfConnected.set(status.connected);
        qfLogin.set(status.login ?? null);
        if (status.connected) await syncFromQf();
    } catch {
        qfConnected.set(false);
    }
}

/** Replace the list with the QF-synced bookmarks (connected mode only). */
export async function syncFromQf(): Promise<void> {
    const resp = await getRemoteBookmarks();
    qfConnected.set(resp.connected);
    if (resp.connected) {
        bookmarks.set(
            resp.bookmarks.map((b) => ({
                surah: b.surah,
                ayah: b.ayah,
                key: b.key,
                addedAt: Date.now(),
            })),
        );
    }
}

export function addBookmark(surah: number, ayah: number): void {
    const key = bookmarkKey(surah, ayah);
    const list = get(bookmarks);
    if (isBookmarked(list, key)) return;
    const next = [makeBookmark(surah, ayah), ...list];
    bookmarks.set(next);
    if (get(qfConnected)) {
        void addRemoteBookmark(surah, ayah).catch(() => {
            /* best-effort; local copy already updated */
        });
    } else {
        persistLocal(next);
    }
}

export function removeBookmark(key: string): void {
    const next = get(bookmarks).filter((b) => b.key !== key);
    bookmarks.set(next);
    if (get(qfConnected)) {
        void removeRemoteBookmark(key).catch(() => {});
    } else {
        persistLocal(next);
    }
}

/** Disconnect from Quran.Foundation: clear the session and return to the
 *  local (localStorage-backed) bookmarks. */
export async function disconnectQf(): Promise<void> {
    try {
        await qfLogout();
    } catch {
        /* clearing is best-effort; fall through to local mode regardless */
    }
    qfConnected.set(false);
    qfLogin.set(null);
    bookmarks.set(loadLocal());
}

export function toggleBookmarksPanel(): void {
    bookmarksVisible.update((v) => !v);
}
