/**
 * Shadow audio element for cross-chapter prewarming.
 *
 * Use case: validation accordion. When the user opens a card whose lead seg
 * is in a DIFFERENT chapter from what `segPort` currently has bound, we
 * can't just call `segPort.prewarm()` — that would either interrupt active
 * playback or rebind the user's main-list playback context. The shadow
 * element side-steps this by pre-loading the URL on a hidden `<audio>`
 * element. Its fetch fills the browser HTTP cache for that URL; when the
 * user later clicks play in the accordion card and `segPort.setSource` +
 * `loadCovering` runs, `el.load()` hits the warm cache → fast canplay.
 *
 * Single shadow element, swapped between URLs. Dedupes within 30s so
 * repeated panel reactives don't refetch.
 *
 * No-op for empty / repeat URLs. Adds the element to `document.body` on
 * first use (some browsers require DOM attachment for `.load()` to fire).
 */

const DEDUPE_MS = 30_000;

let _shadow: HTMLAudioElement | null = null;
let _lastUrl: string | null = null;
let _lastFiredAt = 0;

function _getShadow(): HTMLAudioElement | null {
    if (typeof document === 'undefined') return null;
    if (_shadow) return _shadow;
    const el = document.createElement('audio');
    el.preload = 'auto';
    el.style.display = 'none';
    el.setAttribute('aria-hidden', 'true');
    document.body.appendChild(el);
    _shadow = el;
    return el;
}

/** Pre-load `audioUrl` on a hidden audio element so its bytes land in the
 *  browser HTTP cache. Caller is responsible for passing the already-
 *  wrapped (audio-proxy) URL when applicable. */
export function shadowPrewarm(audioUrl: string): void {
    if (!audioUrl) return;
    const now = performance.now();
    if (_lastUrl === audioUrl && now - _lastFiredAt < DEDUPE_MS) return;
    const el = _getShadow();
    if (!el) return;
    _lastUrl = audioUrl;
    _lastFiredAt = now;
    const trace = typeof localStorage !== 'undefined'
        && localStorage.getItem('insp_warmup_log') === 'true';
    if (trace) {
        const startedAt = performance.now();
        const onCanPlay = (): void => {
            // eslint-disable-next-line no-console
            console.log(`[shadow] canplay in ${Math.round(performance.now() - startedAt)}ms ${audioUrl.slice(-40)}`);
            el.removeEventListener('canplay', onCanPlay);
        };
        el.addEventListener('canplay', onCanPlay, { once: true });
        // eslint-disable-next-line no-console
        console.log(`[shadow] fire ${audioUrl.slice(-40)}`);
    }
    el.src = audioUrl;
    el.load();
}

/** Test-only reset. */
export function _resetShadowForTest(): void {
    _lastUrl = null;
    _lastFiredAt = 0;
    if (_shadow) {
        _shadow.removeAttribute('src');
        _shadow.load();
    }
}
