/**
 * Email-notification preferences client.
 *
 * A signed-in OR anonymous visitor opts into no-reply emails for catalog +
 * workflow events from the "My notifications" envelope modal. This module is the
 * FE half: a typed read/write pair against `/api/me/email-preferences`.
 *
 * The shape is single-sourced from `qua_shared` (`EmailPreferences`, codegen'd
 * into `schemas.ts`); `EmailPrefs` is the all-fields-present view the UI binds to.
 *
 * Scope semantics:
 * - `'off'`     — never email for this event.
 * - `'all'`     — email for every reciter.
 * - `'selected'`— email only for the reciters in `reciters` (the one shared
 *                 selection, reused by every `selected`-mode event).
 *
 * The two riwayah events are booleans gated by the shared `riwayahs` follow
 * list: an enabled flag with an empty follow list emits nothing.
 *
 * Identity model: storage is keyed by the email address, not the HF account, so
 * anonymous visitors can subscribe. On first save the server mints a stable
 * `manage_token` (returned here, cached by the modal). That token re-fetches
 * fresh server state for a returning anonymous visitor and powers the email
 * unsubscribe / "manage" deep-link, keeping the modal consistent with an
 * out-of-band unsubscribe.
 */

import type { EmailPreferences } from '../types/generated/schemas';
import { fetchJson } from './index';

/** Per-event scope for reciter-scoped events. */
export type EmailScope = NonNullable<EmailPreferences['recitation_published']>;

/** The UI view of the prefs — every field present (server fills from defaults). */
export type EmailPrefs = Required<EmailPreferences>;

export const DEFAULT_EMAIL_PREFS: EmailPrefs = {
    email: '',
    request_aligned: false,
    recitation_published: 'off',
    timestamps_regenerated: 'off',
    github_release: false,
    riwayah_new_recitation: false,
    riwayah_first_available: false,
    owner_new_request: false,
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
        owner_new_request: r.owner_new_request === true,
        reciters: asStringArray(r.reciters),
        riwayahs: asStringArray(r.riwayahs),
    };
}

/** A loaded subscription: the prefs plus the manage token (when the row exists). */
export interface LoadedEmailPrefs {
    prefs: EmailPrefs;
    manageToken: string | null;
}

function extractToken(data: Record<string, unknown> | null): string | null {
    return data && typeof data.manage_token === 'string' ? data.manage_token : null;
}

/**
 * Load email preferences. Signed-in callers resolve by their HF cookie; pass a
 * `manageToken` to resolve an anonymous subscription by its token instead
 * (re-fetches fresh server state, e.g. after an out-of-band unsubscribe).
 */
export async function fetchEmailPrefs(
    opts: { signal?: AbortSignal; manageToken?: string | null } = {},
): Promise<LoadedEmailPrefs> {
    const qs = opts.manageToken ? `?token=${encodeURIComponent(opts.manageToken)}` : '';
    const data = await fetchJson<Record<string, unknown>>(`/api/me/email-preferences${qs}`, {
        signal: opts.signal,
    });
    if (data && typeof data === 'object' && 'error' in data && data.error) {
        throw new Error(String(data.error));
    }
    return { prefs: normalizeEmailPrefs(data), manageToken: extractToken(data) };
}

/** Persist preferences. Returns the normalized saved prefs + the manage token. */
export async function saveEmailPrefs(prefs: EmailPrefs): Promise<LoadedEmailPrefs> {
    const data = await fetchJson<Record<string, unknown>>('/api/me/email-preferences', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(prefs),
    });
    if (data && typeof data === 'object' && 'error' in data && data.error) {
        throw new Error(String(data.error));
    }
    return {
        prefs: normalizeEmailPrefs(data && Object.keys(data).length ? data : prefs),
        manageToken: extractToken(data),
    };
}

/** Minimal email-shape check — a single `@` with non-empty local + domain. */
export function isValidEmail(email: string): boolean {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
}
