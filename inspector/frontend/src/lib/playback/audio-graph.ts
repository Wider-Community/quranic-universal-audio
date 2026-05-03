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
 *  when Web Audio is unavailable.
 *
 *  `MediaElementAudioSourceNode` may be constructed only ONCE per audio
 *  element for the lifetime of the page (Web Audio spec) — we cache via
 *  `WeakMap`. After routing, the element's default-output path is replaced
 *  by `source -> gain -> destination`. Disconnecting or zeroing the gain
 *  silences the element completely. */
export function getAudioGraph(el: HTMLAudioElement): AudioGraph | null {
    const cached = _graphs.get(el);
    if (cached) return cached;
    const ctx = _getCtx();
    if (!ctx) return null;
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
