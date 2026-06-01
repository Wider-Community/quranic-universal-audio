/**
 * Timestamps tab — shuffle state (footer control).
 *
 * Surfaced as ONE tri-state cycle control (like the eye/upcoming control),
 * backed by two booleans that stay the source of truth so every consumer
 * (auto-advance, shuffleJump, reprime subscriptions) keeps reading them:
 *   - `shuffleAyah`    — after each ayah ends, jump to a random ayah.
 *   - `shuffleReciter` — the random ayah comes from a random reciter.
 *
 * The cycle is off → ayah (same reciter, random ayahs) → both (random reciter
 * + ayah) → off. `shuffleMode` exposes that as 0/1/2 for the icon.
 *
 * Persisted to localStorage so the choice survives reloads.
 */
import { derived, get, writable } from 'svelte/store';

import { exitLoop } from '../../../lib/playback/loop';

const LS_SHUFFLE_RECITER = 'ts_shuffle_reciter';
const LS_SHUFFLE_AYAH = 'ts_shuffle_ayah';

function load(key: string): boolean {
    try {
        return localStorage.getItem(key) === 'true';
    } catch {
        return false;
    }
}

export const shuffleReciter = writable<boolean>(load(LS_SHUFFLE_RECITER));
export const shuffleAyah = writable<boolean>(load(LS_SHUFFLE_AYAH));
export const manualShuffleRequest = writable<number>(0);

export function requestManualShuffle(): void {
    manualShuffleRequest.update((n) => n + 1);
}

shuffleReciter.subscribe((v) => {
    try {
        localStorage.setItem(LS_SHUFFLE_RECITER, String(v));
    } catch {
        /* ignore */
    }
});
shuffleAyah.subscribe((v) => {
    try {
        localStorage.setItem(LS_SHUFFLE_AYAH, String(v));
    } catch {
        /* ignore */
    }
});

/** Tri-state shuffle for the footer cycle button:
 *    0 = off · 1 = ayah (same reciter, random ayahs) · 2 = both (random
 *    reciter + ayah). Reciter-shuffle always implies ayah-shuffle, so the
 *    `(true, false)` combination never arises. */
export const shuffleMode = derived(
    [shuffleReciter, shuffleAyah],
    ([$reciter, $ayah]) => ($reciter ? 2 : $ayah ? 1 : 0) as 0 | 1 | 2,
);

/** Advance the cycle off → ayah → both → off. Engaging any shuffle state
 *  exits loop mode (it's deliberate navigation away from the looped region). */
export function cycleShuffle(): void {
    const mode = get(shuffleMode);
    if (mode === 0) {
        // off → ayah (same reciter)
        shuffleReciter.set(false);
        shuffleAyah.set(true);
        exitLoop();
    } else if (mode === 1) {
        // ayah → both (random reciter + ayah)
        shuffleReciter.set(true);
        shuffleAyah.set(true);
        exitLoop();
    } else {
        // both → off
        shuffleReciter.set(false);
        shuffleAyah.set(false);
    }
}
