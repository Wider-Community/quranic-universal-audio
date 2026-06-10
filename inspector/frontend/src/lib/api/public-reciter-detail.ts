/**
 * Single-reciter detail fetcher for the dashboard detail page.
 *
 * Resolves to ``null`` on 404 so consumers can render a "not found"
 * state without try/catch ergonomics.
 */
import type { AdminViewReciter, PublicReciter } from '../types/generated/schemas';

/**
 * For anonymous / contributor callers the response matches `PublicReciter`.
 * For maintainer / owner callers it's `AdminViewReciter` with the extra
 * `discarded_deliveries` + `fully_discarded` fields. We type the return as
 * the widened admin shape so component callsites can read those fields
 * safely (they'll be `undefined` for non-admin viewers).
 */
export async function fetchPublicReciter(
    reciterId: string,
    signal?: AbortSignal,
): Promise<(PublicReciter & Partial<AdminViewReciter>) | null> {
    const resp = await fetch(`/api/public/reciter/${encodeURIComponent(reciterId)}`, { signal });
    if (resp.status === 404) return null;
    if (!resp.ok) {
        throw new Error(`fetchPublicReciter: HTTP ${resp.status}`);
    }
    return (await resp.json()) as PublicReciter & Partial<AdminViewReciter>;
}
