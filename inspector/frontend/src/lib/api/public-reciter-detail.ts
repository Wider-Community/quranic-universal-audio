/**
 * Single-reciter detail fetcher for the dashboard detail page.
 *
 * Resolves to ``null`` on 404 so consumers can render a "not found"
 * state without try/catch ergonomics.
 */
import type { PublicReciter } from '../types/public-state';

export async function fetchPublicReciter(
    reciterId: string,
    signal?: AbortSignal,
): Promise<PublicReciter | null> {
    const resp = await fetch(`/api/public/reciter/${encodeURIComponent(reciterId)}`, { signal });
    if (resp.status === 404) return null;
    if (!resp.ok) {
        throw new Error(`fetchPublicReciter: HTTP ${resp.status}`);
    }
    return (await resp.json()) as PublicReciter;
}
