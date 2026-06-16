/**
 * Stable per-browser token for anonymous verse flags.
 *
 * Anonymous visitors have no HF account, so their Timestamps-tab flags are
 * keyed by a random token persisted in localStorage. The same browser can then
 * edit/delete its own comment across refreshes. Signed-in users never use this
 * (their flags key on `hf_user_id`). Best-effort: if localStorage is
 * unavailable a fresh per-session token is returned (edits won't survive a
 * reload, which is acceptable).
 */

import { LS_KEYS } from './constants';

let memo: string | null = null;

function mint(): string {
    try {
        return crypto.randomUUID();
    } catch {
        return `anon-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
    }
}

/** Read the persisted anon token, minting + storing one on first use. */
export function getAnonToken(): string {
    if (memo) return memo;
    try {
        const existing = localStorage.getItem(LS_KEYS.ANON_FLAG_TOKEN);
        if (existing) {
            memo = existing;
            return existing;
        }
        const token = mint();
        localStorage.setItem(LS_KEYS.ANON_FLAG_TOKEN, token);
        memo = token;
        return token;
    } catch {
        memo = mint();
        return memo;
    }
}
