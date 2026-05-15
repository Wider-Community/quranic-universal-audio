/**
 * Quran reference data (`dk_words` + `verse_word_counts`) lives behind one
 * static, content-hashed endpoint instead of being shipped on every reciter
 * switch. The bundle is identical for every user, reciter, chapter, and
 * session, so we fetch it once per browser and share it across tabs via a
 * Svelte store.
 *
 * Boot flow:
 *   1. `loadQuranRefs()` is called from `App.svelte::onMount`.
 *   2. Hit `/api/static/quran-refs/version` (no-cache) for the current hash.
 *   3. Try `sessionStorage` first — same hash means we already have the bytes.
 *   4. Otherwise fetch `/api/static/quran-refs.json?v=<hash>` (immutable).
 *   5. Populate the `quranRefs` store + cache by hash in `sessionStorage`.
 */
import { type Readable,writable } from 'svelte/store';

import { fetchJson } from '../api';

export interface QuranRefs {
    dk_words: Record<string, string>;
    verse_word_counts: Record<string, number>;
}

const _store = writable<QuranRefs | null>(null);
/** Single store consumed everywhere — null until the bundle is fetched. */
export const quranRefs: Readable<QuranRefs | null> = _store;

let _inflight: Promise<void> | null = null;

const SS_PREFIX = 'quran-refs:';

function _readSessionCache(hash: string): QuranRefs | null {
    try {
        const raw = sessionStorage.getItem(SS_PREFIX + hash);
        if (!raw) return null;
        return JSON.parse(raw) as QuranRefs;
    } catch {
        return null;
    }
}

function _writeSessionCache(hash: string, refs: QuranRefs): void {
    try {
        // Drop entries under prior hashes so a long-running session doesn't
        // accumulate stale bundles across deploys.
        for (let i = sessionStorage.length - 1; i >= 0; i -= 1) {
            const k = sessionStorage.key(i);
            if (k && k.startsWith(SS_PREFIX) && k !== SS_PREFIX + hash) {
                sessionStorage.removeItem(k);
            }
        }
        sessionStorage.setItem(SS_PREFIX + hash, JSON.stringify(refs));
    } catch {
        // QuotaExceeded or storage disabled — non-fatal, in-memory store still works.
    }
}

/**
 * Load (or revalidate) the Quran-refs bundle. Idempotent — repeated calls
 * before the first fetch resolves share one in-flight promise.
 */
export function loadQuranRefs(): Promise<void> {
    if (_inflight) return _inflight;
    _inflight = (async () => {
        try {
            const { version } = await fetchJson<{ version: string }>(
                '/api/static/quran-refs/version',
            );
            const cached = _readSessionCache(version);
            if (cached) {
                _store.set(cached);
                return;
            }
            const refs = await fetchJson<QuranRefs>(
                `/api/static/quran-refs.json?v=${encodeURIComponent(version)}`,
            );
            if (!refs || typeof refs !== 'object' || !refs.dk_words) {
                console.error('quran-refs: malformed payload', refs);
                return;
            }
            _writeSessionCache(version, refs);
            _store.set(refs);
        } catch (e) {
            console.error('quran-refs load failed', e);
            // Leave store at `null`; consumers already tolerate that state
            // (same as pre-segAllData hydration). Next reciter switch retries.
            _inflight = null;
        }
    })();
    return _inflight;
}
