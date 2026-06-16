/**
 * Email-notification preferences client.
 *
 * The signed-in user opts into no-reply emails for catalog + workflow events
 * from the "My notifications" envelope modal. This module is the FE half: a
 * typed read/write pair against `/api/me/email-preferences`. The shape here is
 * the contract the backend implements (prefs table + emitter + SMTP are a
 * separate change — see the modal's handoff note).
 *
 * Scope semantics:
 * - `'off'`     — never email for this event.
 * - `'all'`     — email for every reciter.
 * - `'selected'`— email only for the reciters in `reciters` (the one shared
 *                 selection, reused by every `selected`-mode event).
 *
 * The two riwayah events are booleans gated by the shared `riwayahs` follow
 * list: an enabled flag with an empty follow list emits nothing.
 */

import { fetchJson } from './index';

/** Per-event scope for reciter-scoped events. */
export type EmailScope = 'off' | 'all' | 'selected';

export interface EmailPrefs {
    /** Destination address. Seeded server-side from the HF account email on
     *  first load; empty when neither saved nor available. */
    email: string;

    /** A request you submitted finishes alignment and is ready for review. */
    request_aligned: boolean;
    /** A recitation is published (in-app). Reciter-scoped. */
    recitation_published: EmailScope;
    /** A reciter's timestamps are regenerated. Reciter-scoped. */
    timestamps_regenerated: EmailScope;
    /** A new GitHub release is published. */
    github_release: boolean;

    /** A new recitation is published in a riwayah you follow. */
    riwayah_new_recitation: boolean;
    /** A riwayah you follow becomes available — its first ever recitation.
     *  Sent once per riwayah. */
    riwayah_first_available: boolean;

    /** Shared reciter_ids powering every `selected`-mode event above. */
    reciters: string[];
    /** Shared riwayah slugs powering both riwayah events above. */
    riwayahs: string[];
}

export const DEFAULT_EMAIL_PREFS: EmailPrefs = {
    email: '',
    request_aligned: false,
    recitation_published: 'off',
    timestamps_regenerated: 'off',
    github_release: false,
    riwayah_new_recitation: false,
    riwayah_first_available: false,
    reciters: [],
    riwayahs: [],
};

const SCOPES: readonly EmailScope[] = ['off', 'all', 'selected'];

function asScope(v: unknown): EmailScope {
    return typeof v === 'string' && (SCOPES as readonly string[]).includes(v)
        ? (v as EmailScope)
        : 'off';
}

function asStringArray(v: unknown): string[] {
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
}

/**
 * Coerce a raw payload into a complete `EmailPrefs`, filling any missing field
 * from defaults. Keeps the FE resilient to a partial / older server shape and
 * guarantees every consumer reads a fully-populated object.
 */
export function normalizeEmailPrefs(raw: unknown): EmailPrefs {
    const r = (raw ?? {}) as Record<string, unknown>;
    return {
        email: typeof r.email === 'string' ? r.email : '',
        request_aligned: r.request_aligned === true,
        recitation_published: asScope(r.recitation_published),
        timestamps_regenerated: asScope(r.timestamps_regenerated),
        github_release: r.github_release === true,
        riwayah_new_recitation: r.riwayah_new_recitation === true,
        riwayah_first_available: r.riwayah_first_available === true,
        reciters: asStringArray(r.reciters),
        riwayahs: asStringArray(r.riwayahs),
    };
}

/** Load the signed-in user's email preferences. */
export async function fetchEmailPrefs(signal?: AbortSignal): Promise<EmailPrefs> {
    const data = await fetchJson<Record<string, unknown>>('/api/me/email-preferences', { signal });
    if (data && typeof data === 'object' && 'error' in data && data.error) {
        throw new Error(String(data.error));
    }
    return normalizeEmailPrefs(data);
}

/** Persist the user's email preferences. Returns the normalized saved shape. */
export async function saveEmailPrefs(prefs: EmailPrefs): Promise<EmailPrefs> {
    const data = await fetchJson<Record<string, unknown>>('/api/me/email-preferences', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(prefs),
    });
    if (data && typeof data === 'object' && 'error' in data && data.error) {
        throw new Error(String(data.error));
    }
    // Backend echoes the persisted prefs; fall back to what we sent.
    return normalizeEmailPrefs(data && Object.keys(data).length ? data : prefs);
}

/** Minimal email-shape check — a single `@` with non-empty local + domain. */
export function isValidEmail(email: string): boolean {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
}
