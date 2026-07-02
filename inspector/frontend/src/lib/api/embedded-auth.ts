/**
 * Embedded (HF-iframe) sign-in flow.
 *
 * The app runs inside the cross-site `huggingface.co` iframe on a different
 * domain (`*.hf.space`). Two browser constraints shape this (per HF's own docs,
 * https://huggingface.co/docs/hub/spaces-cookie-limitations and
 * https://huggingface.co/docs/hub/spaces-oauth):
 *   - HF's login/consent page can't render inside the iframe (X-Frame-Options),
 *     and the iframe can't navigate the top window (sandbox). So a user who
 *     isn't already logged into HF must authenticate in a separate tab.
 *   - The identity cookie is third-party in the iframe, so it needs the Storage
 *     Access API to be readable.
 *
 * Strategy (no popup):
 *   1. Silent attempt — request storage access, then run the OAuth in a hidden
 *      iframe. For a user already logged into HF this completes as pure
 *      redirects (no page renders) and the cookie becomes readable → signed in
 *      without ever leaving the embedded view.
 *   2. Fallback — if the silent attempt can't complete (not logged into HF, or
 *      the browser blocks the third-party cookie outright), surface a single
 *      "continue in a new tab" link. It has to be a click: browsers block
 *      programmatically opening a tab that isn't tied to a user gesture.
 *
 * Drives `SignInModal`.
 */

import { writable } from 'svelte/store';

import { loadCurrentUser } from '../stores/current-user';

/**
 * - `idle`         — nothing in progress.
 * - `trying`       — silent in-iframe attempt running (brief).
 * - `need-tab`     — silent attempt failed; offer the new-tab link.
 * - `awaiting-tab` — a sign-in tab is open; waiting for the user to return.
 * - `done`         — signed in; the iframe can see the session.
 */
export type EmbeddedAuthPhase = 'idle' | 'trying' | 'need-tab' | 'awaiting-tab' | 'done';

export const embeddedAuth = writable<{ phase: EmbeddedAuthPhase }>({ phase: 'idle' });

const SILENT_TIMEOUT_MS = 6000;
const SILENT_POLL_MS = 800;
const RETURN_POLL_MS = 1500;

let _returnPath = '/';
let _stopWatch: (() => void) | null = null;

function _setPhase(phase: EmbeddedAuthPhase): void {
    embeddedAuth.set({ phase });
}

/** True when running inside another document's frame. A cross-origin parent
 *  makes `window.top` access throw — which itself means we're embedded. */
export function isEmbedded(): boolean {
    try {
        return window.self !== window.top;
    } catch {
        return true;
    }
}

/** First-party URL of this Space in its own tab. */
export function standaloneUrl(returnPath: string): string {
    const path = returnPath && returnPath.startsWith('/') ? returnPath : '/';
    return window.location.origin + path;
}

/** Best-effort Storage Access API grant so the iframe can use its own cookie. */
async function _tryStorageAccess(): Promise<void> {
    try {
        if (typeof document.requestStorageAccess === 'function') {
            await document.requestStorageAccess();
        }
    } catch {
        /* denied — the silent attempt will simply not resolve; we fall back */
    }
}

async function _meLogin(): Promise<string | null> {
    try {
        const me = await fetch('/api/me', { credentials: 'same-origin' }).then((r) => r.json());
        return me && me.hf_user_id ? me.login : null;
    } catch {
        return null;
    }
}

/**
 * Run the OAuth in a hidden iframe and poll `/api/me`. Resolves true if the
 * session becomes readable (already-logged-in HF user + cookie access), false
 * on timeout (not logged into HF, or third-party cookie blocked).
 */
function _attemptSilent(): Promise<boolean> {
    return new Promise((resolve) => {
        const frame = document.createElement('iframe');
        frame.setAttribute('aria-hidden', 'true');
        frame.tabIndex = -1;
        frame.style.cssText = 'position:absolute;width:0;height:0;border:0;left:-9999px;top:-9999px';
        // popup=1 → the callback serves a self-closing page; harmless (and
        // invisible) here, and avoids booting the whole SPA in the hidden frame.
        frame.src = '/api/auth/login?popup=1&return=%2F';
        let settled = false;
        const cleanup = (val: boolean): void => {
            if (settled) return;
            settled = true;
            window.clearInterval(poll);
            window.clearTimeout(timer);
            frame.remove();
            resolve(val);
        };
        const poll = window.setInterval(async () => {
            if (await _meLogin()) cleanup(true);
        }, SILENT_POLL_MS);
        const timer = window.setTimeout(() => cleanup(false), SILENT_TIMEOUT_MS);
        document.body.appendChild(frame);
    });
}

/**
 * Start the embedded sign-in. Call synchronously from the user's click so the
 * storage-access request keeps its user activation.
 */
export async function beginEmbeddedSignIn(returnPath: string): Promise<void> {
    _returnPath = returnPath || '/';
    _setPhase('trying');
    await _tryStorageAccess();
    const ok = await _attemptSilent();
    if (ok) {
        await loadCurrentUser();
        _setPhase('done');
        return;
    }
    _setPhase('need-tab');
}

/**
 * Fallback: open HF sign-in in a new tab. MUST be called from a user click —
 * browsers block programmatically opening a tab without a fresh gesture, which
 * is why this can't be fully automatic.
 */
export function continueInTab(): void {
    window.open(`/api/auth/login?return=${encodeURIComponent(_returnPath)}`, '_blank');
    _setPhase('awaiting-tab');
    _watchForReturn();
}

/** After the tab login, pick up the session when the user returns to this view. */
function _watchForReturn(): void {
    _clearWatch();
    const check = async (): Promise<void> => {
        await _tryStorageAccess();
        if (await _meLogin()) {
            _clearWatch();
            await loadCurrentUser();
            _setPhase('done');
        }
    };
    const onVisible = (): void => {
        if (document.visibilityState === 'visible') void check();
    };
    window.addEventListener('focus', check);
    document.addEventListener('visibilitychange', onVisible);
    const poll = window.setInterval(check, RETURN_POLL_MS);
    _stopWatch = () => {
        window.removeEventListener('focus', check);
        document.removeEventListener('visibilitychange', onVisible);
        window.clearInterval(poll);
    };
}

function _clearWatch(): void {
    if (_stopWatch) {
        _stopWatch();
        _stopWatch = null;
    }
}

/** Manually re-check (the "I've signed in" button on the awaiting-tab step). */
export async function recheckSession(): Promise<void> {
    await _tryStorageAccess();
    if (await _meLogin()) {
        _clearWatch();
        await loadCurrentUser();
        _setPhase('done');
    }
}

/** Reset to idle and drop any watchers (on modal close). */
export function resetEmbeddedAuth(): void {
    _clearWatch();
    _setPhase('idle');
}
