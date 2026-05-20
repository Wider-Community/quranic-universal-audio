/**
 * Bookmarks + Quran.Foundation connection API client.
 *
 * Backend proxies user bookmarks to QF (`/auth/v1/bookmarks`) when a
 * `qf_session` cookie exists; otherwise the app stays in local mode. These
 * wrappers mirror the `lib/api` conventions.
 */

import { fetchJson } from './index';

export interface RemoteBookmark {
    surah: number;
    ayah: number;
    key: string;
}

interface BookmarksResponse {
    bookmarks: RemoteBookmark[];
    connected: boolean;
    error?: string;
}

interface QfStatus {
    connected: boolean;
    login?: string | null;
    dev?: boolean;
}

export async function getQfStatus(): Promise<QfStatus> {
    return fetchJson<QfStatus>('/api/qf/status');
}

export async function getRemoteBookmarks(): Promise<BookmarksResponse> {
    return fetchJson<BookmarksResponse>('/api/bookmarks');
}

export async function addRemoteBookmark(surah: number, ayah: number): Promise<void> {
    await fetchJson('/api/bookmarks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ surah, ayah }),
    });
}

export async function removeRemoteBookmark(key: string): Promise<void> {
    await fetchJson(`/api/bookmarks/${encodeURIComponent(key)}`, { method: 'DELETE' });
}

/** Dev-only: mint a synthetic qf_session to exercise the proxy locally. */
export async function devConnectQf(): Promise<void> {
    await fetchJson('/api/qf/dev-login', { method: 'POST' });
}
