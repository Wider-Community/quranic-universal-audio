/**
 * Cross-tab deep-link channel.
 *
 * `pendingTsNavigation` is set by callers outside the Timestamps tab (e.g. the
 * Bookmarks sidebar) to request that the Timestamps tab load a specific verse
 * with a random reciter and autoplay. TimestampsTab consumes and clears it.
 */

import { writable } from 'svelte/store';

export interface PendingTsNavigation {
    surah: number;
    ayah: number;
    autoplay: boolean;
}

export const pendingTsNavigation = writable<PendingTsNavigation | null>(null);
