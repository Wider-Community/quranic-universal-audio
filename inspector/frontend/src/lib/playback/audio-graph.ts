/**
 * Web Audio kill-switch — sample-accurate gain ramp before the OS sink.
 *
 * `HTMLAudioElement.pause()` halts the source-side renderer pushing samples
 * into the platform output queue, but does NOT flush samples already handed
 * to the OS audio device. On Windows WASAPI shared mode the queue typically
 * holds 50–200 ms of pre-decoded audio (up to 300 ms on Bluetooth), so
 * pausing at the end of a segment leaves an audible "tail" of audio from
 * positions past `time_end`. Setting `audio.muted = true` and
 * `audio.volume = 0` both apply source-side and DON'T silence the queue.
 *
 * The fix: route the existing `<audio>` element through the Web Audio graph
 * (`MediaElementAudioSourceNode -> GainNode -> destination`) and use a
 * 5 ms `linearRampToValueAtTime(0)` as the kill-switch. Web Audio applies
 * gain on the AudioContext render quantum, _before_ the platform sink, so
 * the audible tail drops to roughly `outputLatency` (~20–30 ms wired). The
 * 5 ms ramp avoids click-pop artifacts.
 *
 * Howler.js defaults to this pattern for the same reason.
 */

interface AudioGraph {
    ctx: AudioContext;
    source: MediaElementAudioSourceNode;
    gain: GainNode;
}

const _graphs = new WeakMap<HTMLAudioElement, AudioGraph>();
let _ctx: AudioContext | null = null;
let _ctxUnavailable = false;

function _audioContextCtor(): typeof AudioContext | null {
    const w = globalThis as { AudioContext?: typeof AudioContext };
    return w.AudioContext ?? null;
}

/** Lazy-init a single AudioContext shared across all elements.
 *
 *  Exported for `audio-warmup.ts` to bootstrap inside a user-gesture
 *  handler so Chrome's autoplay policy doesn't leave us in `suspended`.
 *
 *  Returns `null` if `AudioContext` is unavailable in this environment
 *  (e.g. test runners that don't shim Web Audio). Callers must treat
 *  null as "no kill-switch available" and fall back to the source-side
 *  pause(). The audible-tail bug returns in that fallback path. */
export function _getCtx(): AudioContext | null {
    if (_ctx) return _ctx;
    if (_ctxUnavailable) return null;
    const Ctor = _audioContextCtor();
    if (!Ctor) {
        _ctxUnavailable = true;
        return null;
    }
    try {
        _ctx = new Ctor();
        return _ctx;
    } catch {
        _ctxUnavailable = true;
        return null;
    }
}

/** Return the AudioGraph for `el`, building it lazily. Returns `null`
 *  when Web Audio is unavailable OR when the AudioContext isn't running yet.
 *
 *  CRITICAL: `MediaElementAudioSourceNode` redirects the element's audio
 *  output to the Web Audio graph the instant it's constructed. If we built
 *  the graph while the context was `suspended` (Chrome's autoplay policy
 *  state), the element's audio would route to a graph that produces no
 *  output — silence even after the context later resumed. So we refuse
 *  to construct the graph until `ctx.state === 'running'`. The kill-
 *  switch silently no-ops on the very first play (when the warmup may
 *  still be resuming the context); subsequent plays get the kill-switch.
 *
 *  `MediaElementAudioSourceNode` may be constructed only ONCE per element
 *  for the lifetime of the page (Web Audio spec) — we cache via WeakMap. */
export function getAudioGraph(el: HTMLAudioElement): AudioGraph | null {
    const cached = _graphs.get(el);
    if (cached) return cached;
    const ctx = _getCtx();
    if (!ctx) return null;
    if (ctx.state !== 'running') {
        // Don't route the element through Web Audio while the context is
        // suspended/closed — that would silence the next play(). Try to
        // resume; the first invocation of cutAudio/uncutAudio that lands
        // when the context is finally running will build the graph.
        if (ctx.state === 'suspended') void ctx.resume();
        return null;
    }
    const source = ctx.createMediaElementSource(el);
    const gain = ctx.createGain();
    source.connect(gain).connect(ctx.destination);
    const g: AudioGraph = { ctx, source, gain };
    _graphs.set(el, g);
    return g;
}

function _resumeIfSuspended(ctx: AudioContext): void {
    if (ctx.state === 'suspended') void ctx.resume();
}

/** Resume the shared AudioContext if suspended. Safe no-op when Web Audio
 *  is unavailable or the context is already running. Awaits the resume so
 *  the caller can sequence ``audio.play()`` immediately after — fixes the
 *  "progress moves but no audio" case after a tab switch. */
export async function ensureAudioContextRunning(): Promise<void> {
    const ctx = _getCtx();
    if (!ctx) return;
    if (ctx.state === 'suspended') {
        try {
            await ctx.resume();
        } catch {
            // Browser may reject if no user gesture is active. The caller's
            // play() will still produce audio via the element's default path
            // until the graph is wired on a later, gesture-bound play.
        }
    }
}

/** Schedule a fast (5 ms) gain ramp to 0. Cancels any pending ramp first.
 *  Click-free; sample-accurate at the AudioContext quantum. No-op if
 *  Web Audio is unavailable. */
export function cutAudio(el: HTMLAudioElement): void {
    const g = getAudioGraph(el);
    if (!g) return;
    _resumeIfSuspended(g.ctx);
    const now = g.ctx.currentTime;
    g.gain.gain.cancelScheduledValues(now);
    g.gain.gain.setValueAtTime(g.gain.gain.value, now);
    g.gain.gain.linearRampToValueAtTime(0, now + 0.005);
}

/** Restore gain to 1 over 5 ms. Called before `audio.play()` resumes so
 *  the next playback fades in cleanly without a plosive. No-op if
 *  Web Audio is unavailable. */
export function uncutAudio(el: HTMLAudioElement): void {
    const g = getAudioGraph(el);
    if (!g) return;
    _resumeIfSuspended(g.ctx);
    const now = g.ctx.currentTime;
    g.gain.gain.cancelScheduledValues(now);
    g.gain.gain.setValueAtTime(g.gain.gain.value, now);
    g.gain.gain.linearRampToValueAtTime(1, now + 0.005);
}
