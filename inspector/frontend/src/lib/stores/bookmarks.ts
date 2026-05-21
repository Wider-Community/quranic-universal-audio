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
/** True when the active session is the local dev stub (not a real QF login). */
export const qfDev = writable<boolean>(false);

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
        qfDev.set(Boolean(status.dev));
        if (status.connected) {
            // A `?qf_connected=1` landing means we just returned from a
            // full-page OAuth (popup coerced to same-tab, e.g. in the HF
            // iframe). Treat it as a fresh connect → merge local up, then
            // strip the flag so reloads don't re-merge.
            if (consumeFreshConnectFlag()) {
                await onQfConnected();
            } else {
                await syncFromQf();
            }
        }
    } catch {
        qfConnected.set(false);
    }
}

function consumeFreshConnectFlag(): boolean {
    if (typeof window === 'undefined') return false;
    const params = new URLSearchParams(window.location.search);
    if (params.get('qf_connected') !== '1') return false;
    params.delete('qf_connected');
    const qs = params.toString();
    const url = window.location.pathname + (qs ? `?${qs}` : '') + window.location.hash;
    window.history.replaceState({}, '', url);
    return true;
}

/**
 * Called once at the moment of connecting: merge the browser's local bookmarks
 * up into the QF account (push any the account doesn't already have), then show
 * the synced account list. Runs only on connect — not on every load — so it
 * never resurrects bookmarks the user later deletes from their account.
 */
export async function onQfConnected(): Promise<void> {
    qfConnected.set(true);
    const local = get(bookmarks);
    try {
        const remote = await getRemoteBookmarks();
        if (remote.connected) {
            const remoteKeys = new Set(remote.bookmarks.map((b) => b.key));
            const toPush = local.filter((b) => !remoteKeys.has(b.key));
            await Promise.all(
                toPush.map((b) => addRemoteBookmark(b.surah, b.ayah).catch(() => {})),
            );
        }
    } catch {
        /* merge is best-effort; fall through to a plain sync */
    }
    await syncFromQf();
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
    qfDev.set(false);
    bookmarks.set(loadLocal());
}

export function toggleBookmarksPanel(): void {
    bookmarksVisible.update((v) => !v);
}
