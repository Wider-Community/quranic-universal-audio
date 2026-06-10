/**
 * Audio-surahs fetcher — wraps ``/api/audio/surahs/<category>/<source>/<slug>``.
 *
 * Returns ``{surahNum → {url, durationMs}}`` for a delivery. ``durationMs``
 * comes from the sidecar so the dashboard's progress bar can show full
 * chapter length even with ``<audio preload="none">`` (the element doesn't
 * fetch MP3 headers until the user hits play).
 */

import type { AudioSurahsResponse } from '../types/generated/schemas';

export interface SurahEntry {
    url: string;
    durationMs: number | null;
    /** Routing tag from the backend: ``qf_api`` when the URL came from the
     * Quran.Foundation Content API, ``qf_fallback`` when an attempt fell back
     * to our own link. Absent for un-routed deliveries. */
    via?: 'qf_api' | 'qf_fallback';
    /** Our original CDN link, present only when ``via === 'qf_api'``. */
    originUrl?: string;
}

const _cache: Map<string, Record<string, SurahEntry>> = new Map();

export async function fetchSurahsForDelivery(
    source: string,
    slug: string,
    signal?: AbortSignal,
): Promise<Record<string, SurahEntry>> {
    const key = `by_surah/${source}/${slug}`;
    const cached = _cache.get(key);
    if (cached) return cached;
    const resp = await fetch(`/api/audio/surahs/${key}`, { signal });
    if (!resp.ok) {
        throw new Error(`fetchSurahsForDelivery: HTTP ${resp.status}`);
    }
    const data = (await resp.json()) as AudioSurahsResponse;
    const raw = data.surahs ?? {};
    const out: Record<string, SurahEntry> = {};
    for (const [k, entry] of Object.entries(raw)) {
        // `AudioSurahEntry` is an open `{ [k]: unknown }` map server-side; the
        // route emits these typed fields per chapter.
        const v = entry as {
            url: string;
            duration_ms: number | null;
            via?: 'qf_api' | 'qf_fallback';
            origin_url?: string;
        };
        out[k] = { url: v.url, durationMs: v.duration_ms, via: v.via, originUrl: v.origin_url };
    }
    _cache.set(key, out);
    return out;
}
