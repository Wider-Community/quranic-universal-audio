/**
 * Audio-surahs fetcher — wraps ``/api/audio/surahs/<category>/<source>/<slug>``.
 *
 * Returns a surah-number → audio-URL map for a delivery. The Phase 6
 * BottomPlayer is by-surah only; ayah-level wiring stays in the Audio
 * tab's archive history (not exposed in dashboard).
 */

interface AudioSurahsResponse {
    surahs: Record<string, string>;
}

const _cache: Map<string, Record<string, string>> = new Map();

export async function fetchSurahsForDelivery(
    source: string,
    slug: string,
    signal?: AbortSignal,
): Promise<Record<string, string>> {
    const key = `by_surah/${source}/${slug}`;
    const cached = _cache.get(key);
    if (cached) return cached;
    const resp = await fetch(`/api/audio/surahs/${key}`, { signal });
    if (!resp.ok) {
        throw new Error(`fetchSurahsForDelivery: HTTP ${resp.status}`);
    }
    const data = (await resp.json()) as AudioSurahsResponse;
    const surahs = data.surahs ?? {};
    _cache.set(key, surahs);
    return surahs;
}
