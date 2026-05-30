/**
 * Shadow audio element pool — owns the warm `<audio>` elements that prewarm
 * upcoming verse plays AND get adopted as the active playback element on
 * consume.
 *
 * Two slots: 'same' (random-current pre-roll) and 'any' (random-any pre-roll).
 * Each slot holds a hidden `<audio crossorigin='anonymous' preload='auto'>`
 * loaded with a URL and seeked to the verse start, so by the time the user
 * clicks Random / auto-advance fires:
 *   - the bytes around the verse start are in browser HTTP cache, AND
 *   - the MP3 decoder is warm at that file position.
 *
 * The historical "fill the HTTP cache" variant (which still left the visible
 * `<audio>` to re-decode the chapter from byte 0 → seek → decode at verse
 * position) is replaced by a hand-off: `consumeWarm(url)` returns the
 * already-decoded element so the caller can transplant it into the visible
 * slot. The previously-visible element rotates back into the pool as the
 * idle warm slot — the `MediaElementAudioSourceNode` it already owns travels
 * with the element (Web Audio spec: one node per element for the lifetime
 * of the page), so the kill-switch graph survives every rotation.
 *
 * Same-URL dedupe within 30 s on each slot so reactive callbacks that
 * recompute the pre-roll don't refetch.
 */

const DEDUPE_MS = 30_000;

type SlotKey = 'same' | 'any';

interface Slot {
    el: HTMLAudioElement;
    /** URL the element is currently warmed for (or null). */
    url: string | null;
    /** Verse start (seconds) the element seeked to during prewarm. Used as
     *  a hint when consuming — the consumer may override the seek target. */
    seekSec: number;
    /** Last prewarm wall-clock for dedupe. */
    lastFiredAt: number;
}

const _slots = new Map<SlotKey, Slot>();

function _trace(): boolean {
    return typeof localStorage !== 'undefined'
        && localStorage.getItem('insp_warmup_log') === 'true';
}

/** Create a hidden `<audio>` element with the same attributes the visible
 *  Timestamps `<AudioElement>` uses, so a transplant is invisible to the user
 *  AND the Web Audio kill-switch keeps working post-swap (it relies on
 *  `crossorigin='anonymous'`).
 *
 *  Created with `controls=false` and `hidden=true`; the caller flips both
 *  when promoting the element to "visible". */
function _makeAudioEl(): HTMLAudioElement {
    const el = document.createElement('audio');
    el.preload = 'auto';
    el.crossOrigin = 'anonymous';
    el.hidden = true;
    el.style.display = 'none';
    el.setAttribute('aria-hidden', 'true');
    document.body.appendChild(el);
    return el;
}

function _getSlot(key: SlotKey): Slot | null {
    if (typeof document === 'undefined') return null;
    let s = _slots.get(key);
    if (s) return s;
    s = { el: _makeAudioEl(), url: null, seekSec: 0, lastFiredAt: 0 };
    _slots.set(key, s);
    return s;
}

/** Pre-load `audioUrl` on the slot's hidden audio element and seek to
 *  `seekSec` so the decoder warms at the verse position (not byte 0).
 *
 *  No-op when the same `(slot, url, seekSec)` was warmed in the last 30 s.
 *  Caller passes the already-wrapped (audio-proxy) URL when applicable. */
export function shadowPrewarm(
    audioUrl: string,
    opts: { slot?: SlotKey; seekSec?: number } = {},
): void {
    if (!audioUrl) return;
    const key: SlotKey = opts.slot ?? 'any';
    const seekSec = Math.max(0, opts.seekSec ?? 0);
    const slot = _getSlot(key);
    if (!slot) return;
    const now = performance.now();
    if (slot.url === audioUrl
        && Math.abs(slot.seekSec - seekSec) < 0.01
        && now - slot.lastFiredAt < DEDUPE_MS) return;

    slot.url = audioUrl;
    slot.seekSec = seekSec;
    slot.lastFiredAt = now;

    const trace = _trace();
    const startedAt = performance.now();
    if (trace) {

        console.log(`[shadow:${key}] fire seek=${seekSec.toFixed(2)}s ${audioUrl.slice(-50)}`);
    }

    const el = slot.el;
    // Set src first, then seek on `loadedmetadata` — currentTime before
    // metadata is loaded silently does nothing on most browsers. Also start
    // a one-shot canplay listener for the trace log.
    const onMeta = (): void => {
        el.removeEventListener('loadedmetadata', onMeta);
        if (seekSec > 0 && Number.isFinite(el.duration) && seekSec < el.duration) {
            try { el.currentTime = seekSec; } catch { /* ignore */ }
        }
    };
    const onCanPlay = (): void => {
        el.removeEventListener('canplay', onCanPlay);
        if (trace) {

            console.log(`[shadow:${key}] canplay in ${Math.round(performance.now() - startedAt)}ms`);
        }
    };
    el.addEventListener('loadedmetadata', onMeta);
    el.addEventListener('canplay', onCanPlay);
    el.src = audioUrl;
    el.load();
}

/** If a warm slot's URL matches `audioUrl`, hand the element back to the
 *  caller AND swap in a fresh empty `<audio>` as the new slot element (so
 *  the slot is ready to be re-warmed). The CALLER takes ownership of the
 *  returned element and is responsible for inserting it into the visible
 *  DOM position; before returning, this helper clears the `hidden`/aria
 *  attrs so the element is visible-ready.
 *
 *  Returns null when no slot matches. */
export function consumeWarm(audioUrl: string): HTMLAudioElement | null {
    if (!audioUrl) return null;
    for (const [key, slot] of _slots) {
        if (slot.url !== audioUrl) continue;
        const warm = slot.el;
        // Replace the slot's element with a fresh idle one so subsequent
        // prewarms have a target. The consumed element becomes the caller's.
        slot.el = _makeAudioEl();
        slot.url = null;
        slot.seekSec = 0;
        slot.lastFiredAt = 0;

        warm.hidden = false;
        warm.style.display = '';
        warm.removeAttribute('aria-hidden');
        if (_trace()) {

            console.log(`[shadow:${key}] consume ${audioUrl.slice(-50)} readyState=${warm.readyState}`);
        }
        return warm;
    }
    return null;
}

/** Demote an element back into the 'any' slot as the new idle warm element.
 *  The previous slot element (if any) gets torn down. Use this when adopting
 *  a warm element via `consumeWarm` — pass the formerly-visible element so
 *  it returns to the pool for the next rotation. */
export function recycleAsShadow(el: HTMLAudioElement, slot: SlotKey = 'any'): void {
    if (!el) return;
    // Detach src + hide. The element's `MediaElementAudioSourceNode` graph
    // (if any) survives — Web Audio caches it in a WeakMap keyed on the
    // element, so the kill-switch wiring travels with the element across
    // rotations.
    el.pause();
    el.removeAttribute('src');
    el.load();
    el.hidden = true;
    el.style.display = 'none';
    el.setAttribute('aria-hidden', 'true');
    // Remove `controls` so the user-visible chrome doesn't briefly flash on
    // an off-screen element when the browser repaints.
    el.removeAttribute('controls');
    if (!document.body.contains(el)) document.body.appendChild(el);

    const existing = _slots.get(slot);
    if (existing) {
        // Tear down the prior slot element so we don't leak; replace with the
        // recycled one (which we know has a graph already wired — it's been
        // through play/pause via the kill-switch).
        const prior = existing.el;
        if (prior !== el && document.body.contains(prior)) {
            prior.removeAttribute('src');
            try { prior.load(); } catch { /* ignore */ }
            prior.remove();
        }
        existing.el = el;
        existing.url = null;
        existing.seekSec = 0;
        existing.lastFiredAt = 0;
    } else {
        _slots.set(slot, { el, url: null, seekSec: 0, lastFiredAt: 0 });
    }
}

/** Test-only reset. Tears down both slots so unit tests start fresh. */
export function _resetShadowForTest(): void {
    for (const slot of _slots.values()) {
        try { slot.el.remove(); } catch { /* ignore */ }
    }
    _slots.clear();
}
