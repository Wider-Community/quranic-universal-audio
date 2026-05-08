/**
 * AudioPort — single chokepoint for audio-element transport.
 *
 * Owns the `<audio>` element, the src-swap decision (chapter MP3 vs.
 * per-segment server clip), and the offset bookkeeping that lets every
 * caller speak file-absolute milliseconds against a logical `AudioSource`,
 * regardless of whether the underlying transport is CBR (chapter URL,
 * file-absolute `currentTime`) or VBR (server-clip URL, clip-relative
 * `currentTime` + `offsetMs` to recover file-absolute).
 *
 * Why the abstraction: VBR-MP3 chapters can't be byte-seeked in their
 * full chapter URL (no Xing header → mis-seeks), so we route per-segment
 * clips through `/api/seg/segment-clip/<reciter>?...`. The clip plays
 * from byte 0; `offsetMs` recovers file-absolute time. Without this port,
 * the clip-vs-full distinction leaked into every editing surface — seek
 * handlers, edit-mode preview, save-preview, history. After this port,
 * all callers speak file-absolute time and never see the transport.
 *
 * Composes existing infra:
 *   - `lib/utils/audio.ts::safePlay` / `audioSrcMatches`
 *   - `lib/playback/audio-graph.ts::cutAudio` / `uncutAudio`
 *
 * No tab-specific store imports — every consumer hands the port its own
 * `AudioSource` via `setSource(...)`, so the port is reusable across the
 * segments, timestamps, and audio tabs (and per-panel preview ports).
 */

import { audioSrcMatches, safePlay } from '../utils/audio';
import { cutAudio, uncutAudio } from './audio-graph';

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/** Logical audio source. Distinct from `<audio>.src` (which is a transport
 *  detail); callers describe the source they want to play, the port picks
 *  the actual URL. */
export interface AudioSource {
    /** Canonical CDN URL — used for VBR clip URL building. The clip
     *  endpoint expects the unwrapped URL in its query string. */
    audioUrl: string;
    /** What to set as `<audio>.src` in CBR mode. Defaults to `audioUrl`
     *  when omitted. Callers that need an audio-proxy wrap (for CORS on
     *  by_surah reciters) compute the wrapped URL and pass it here; the
     *  port doesn't second-guess. VBR mode ignores this field — the clip
     *  endpoint is always built from `audioUrl`. */
    cbrSrc?: string;
    /** Reciter slug. Required for VBR clip routing. null disables it
     *  (port falls through to CBR using `cbrSrc ?? audioUrl`). */
    reciter: string | null;
    /** When true, `loadCovering` builds a server-clip URL for the requested
     *  window. Set from `segData.vbr` (or whatever per-source store carries
     *  the chapter's encoding flag). */
    vbr: boolean;
}

/** Snapshot of what the audio element currently has loaded. */
export interface LoadedWindow {
    /** File-absolute ms of the loaded resource's start. 0 for CBR. */
    startMs: number;
    /** File-absolute ms of the loaded resource's end. Infinity for CBR
     *  (the chapter file covers everything inside its real duration). */
    endMs: number;
    /** ms to add to `audioEl.currentTime * 1000` to get file-absolute time.
     *  0 for CBR; equals `startMs` for VBR clip loads. */
    offsetMs: number;
    /** The actual URL the audio element holds (post-proxy-wrap for CBR). */
    src: string;
    /** True when the loaded src is a server clip (VBR routing). */
    isClip: boolean;
}

/** Returned by `loadCovering`. `ready` resolves on canplay (or sync if
 *  no swap happened). `swapped` lets callers tell instantly whether they
 *  need to await. */
export interface LoadCoveringResult {
    ready: Promise<void>;
    swapped: boolean;
    window: LoadedWindow;
}

export interface AudioPortOptions {
    /** Default coverage padding (ms) added to each side of every
     *  `loadCovering` call when the caller doesn't pass one. CBR ignores;
     *  VBR uses to widen clip windows so subsequent in-window operations
     *  don't trigger a fresh ffmpeg invocation. Default 0. */
    defaultPadMs?: number;
}

type Unsub = () => void;

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Construct the `/api/seg/segment-clip/<reciter>?…` URL.
 *
 *  Deterministic on (reciter, audioUrl, startMs, endMs) so the browser HTTP
 *  cache absorbs repeat plays of the same window. Mirrors the helper that
 *  used to live in `tabs/segments/utils/playback/range-spec.ts` — moved
 *  here so the port owns clip URL construction end-to-end. */
function buildClipUrl(reciter: string, audioUrl: string, startMs: number, endMs: number): string {
    const params = new URLSearchParams({
        url: audioUrl,
        start_ms: String(startMs),
        end_ms: String(endMs),
    });
    return `/api/seg/segment-clip/${encodeURIComponent(reciter)}?${params.toString()}`;
}

function isAbortError(e: unknown): boolean {
    return !!e && typeof e === 'object' && (e as { name?: string }).name === 'AbortError';
}

// ---------------------------------------------------------------------------
// AudioPort
// ---------------------------------------------------------------------------

export class AudioPort {
    private el: HTMLAudioElement | null = null;
    private _source: AudioSource | null = null;
    private _window: LoadedWindow | null = null;
    private readonly defaultPadMs: number;

    /** Bumped on every src swap. Pending canplay handlers compare this
     *  against the gen they captured at attach-time; mismatched gens are
     *  silently dropped. Lets a newer `loadCovering` cancel an older one. */
    private loadGen = 0;
    private pendingCanplay: (() => void) | null = null;
    private pendingReady: { resolve: () => void; reject: (e: unknown) => void } | null = null;

    /** DOM listeners attached on `attachElement` and detached on
     *  `attachElement(null)`. Kept so we can re-emit through subscribers
     *  with file-absolute time on timeupdate. */
    private domListeners: Array<[string, EventListener]> = [];

    private loadSubs = new Set<(w: LoadedWindow) => void>();
    private playSubs = new Set<() => void>();
    private pauseSubs = new Set<() => void>();
    private endedSubs = new Set<() => void>();
    private timeUpdateSubs = new Set<(fileMs: number) => void>();
    private errorSubs = new Set<(err: MediaError | null) => void>();

    constructor(opts: AudioPortOptions = {}) {
        this.defaultPadMs = opts.defaultPadMs ?? 0;
    }

    // -----------------------------------------------------------------------
    // Lifecycle
    // -----------------------------------------------------------------------

    /** Bind to an `<audio>` element. Pass `null` to detach.
     *
     *  Reattaching to a different element auto-detaches the prior one and
     *  cancels any pending canplay (the prior load's `ready` rejects with
     *  AbortError). Idempotent for the same element. */
    attachElement(el: HTMLAudioElement | null): void {
        if (el === this.el) return;
        if (this.el) {
            this._detachDomListeners();
            this._abortPendingLoad();
            this._window = null;
        }
        this.el = el;
        if (el) this._attachDomListeners(el);
    }

    get element(): HTMLAudioElement | null {
        return this.el;
    }

    /** Tear down: detach element, cancel pending load, drop subscribers.
     *  After dispose the port is unusable; construct a fresh one to reuse. */
    dispose(): void {
        this.attachElement(null);
        this.loadSubs.clear();
        this.playSubs.clear();
        this.pauseSubs.clear();
        this.endedSubs.clear();
        this.timeUpdateSubs.clear();
        this.errorSubs.clear();
    }

    // -----------------------------------------------------------------------
    // Source binding
    // -----------------------------------------------------------------------

    /** Bind a logical source. Calling with a different `(audioUrl, reciter,
     *  vbr)` triple invalidates the current window and aborts any pending
     *  load. Calling with the same triple is a no-op. Pass `null` to
     *  detach the current source and clear the audio element's src. */
    setSource(src: AudioSource | null): void {
        if (this._sameSource(src)) return;
        this._abortPendingLoad();
        this._window = null;
        this._source = src;
        if (!src && this.el) {
            this.el.src = '';
            // Mirror existing `chapter-actions.ts` semantics — clearing src
            // followed by load() ensures the element forgets the prior
            // resource cleanly across browsers.
            this.el.load();
        }
    }

    get source(): AudioSource | null {
        return this._source;
    }

    private _sameSource(b: AudioSource | null): boolean {
        const a = this._source;
        if (a === b) return true;
        if (!a || !b) return false;
        return a.audioUrl === b.audioUrl && a.reciter === b.reciter && a.vbr === b.vbr;
    }

    // -----------------------------------------------------------------------
    // Coverage / loading
    // -----------------------------------------------------------------------

    /** Ensure the audio element has a src that covers the requested
     *  file-absolute window. Idempotent — if the current `_window` already
     *  covers `[startMs - pad, endMs + pad]`, returns a sync-resolved
     *  `ready` and `swapped: false`. Otherwise swaps the src, attaches a
     *  canplay listener, and resolves `ready` when canplay fires.
     *
     *  Padding is per-call — not stored. A subsequent zero-pad call that
     *  fits inside the existing wider window no-ops correctly.
     *
     *  Throws if no element is attached or no source is bound. */
    loadCovering(startMs: number, endMs: number, pad?: number): LoadCoveringResult {
        if (!this.el) throw new Error('AudioPort.loadCovering: no element attached');
        if (!this._source) throw new Error('AudioPort.loadCovering: no source bound');
        // Allow `endMs = Infinity` for callers that just want "anything in
        // the file" coverage (Audio-tab full-file play). startMs must be
        // finite and not greater than endMs.
        if (!Number.isFinite(startMs) || Number.isNaN(endMs) || startMs > endMs) {
            throw new Error(`AudioPort.loadCovering: bad range [${startMs}, ${endMs}]`);
        }

        const padMs = pad ?? this.defaultPadMs;
        const needStart = startMs - padMs;
        const needEnd = endMs + padMs;
        const src = this._source;

        // VBR routing. We need a per-segment clip; only swap when the
        // current loaded clip doesn't cover the requested span.
        if (src.vbr && src.reciter && src.audioUrl) {
            if (this._window?.isClip
                && this._window.startMs <= needStart
                && this._window.endMs >= needEnd) {
                return { ready: Promise.resolve(), swapped: false, window: this._window };
            }
            const clipStart = Math.max(0, needStart);
            const clipEnd = needEnd;
            const url = buildClipUrl(src.reciter, src.audioUrl, clipStart, clipEnd);
            return this._swapTo(url, {
                startMs: clipStart,
                endMs: clipEnd,
                offsetMs: clipStart,
                src: url,
                isClip: true,
            });
        }

        // CBR fast path: chapter URL covers the whole file. If the element
        // already holds the chapter src, no-op. Caller-supplied `cbrSrc`
        // wins over the canonical `audioUrl` (so callers needing the
        // audio-proxy wrap pass it pre-wrapped).
        const cbrSrc = src.cbrSrc ?? src.audioUrl;
        // Compare against the live element src as a fallback when no
        // `_window` exists yet — this handles remount-with-loaded-src
        // and the test fixture where the element starts with the same
        // src; without it we'd issue a redundant src-swap waiting on a
        // canplay that may never re-fire.
        const existingSrc = this._window?.src ?? this.el.src;
        if (existingSrc && audioSrcMatches(existingSrc, cbrSrc)) {
            // Synthesize the window so subsequent calls hit the fast path.
            this._window = {
                startMs: 0,
                endMs: Number.POSITIVE_INFINITY,
                offsetMs: 0,
                src: cbrSrc,
                isClip: false,
            };
            return { ready: Promise.resolve(), swapped: false, window: this._window };
        }
        return this._swapTo(cbrSrc, {
            startMs: 0,
            endMs: Number.POSITIVE_INFINITY,
            offsetMs: 0,
            src: cbrSrc,
            isClip: false,
        });
    }

    /** True when the current loaded window covers `[startMs, endMs]` (no
     *  pad). Useful for callers that want to decide whether a fresh
     *  `loadCovering` call is necessary (e.g. trim drag handlers). */
    covers(startMs: number, endMs: number): boolean {
        const w = this._window;
        if (!w) return false;
        return w.startMs <= startMs && w.endMs >= endMs;
    }

    get window(): LoadedWindow | null {
        return this._window;
    }

    // -----------------------------------------------------------------------
    // Coordinate translation (file-absolute outside, clip-relative inside)
    // -----------------------------------------------------------------------

    toClipMs(fileMs: number): number {
        const off = this._window?.offsetMs ?? 0;
        return fileMs - off;
    }

    toFileMs(clipMs: number): number {
        const off = this._window?.offsetMs ?? 0;
        return clipMs + off;
    }

    /** File-absolute current time in ms. Returns 0 when no element is
     *  attached. */
    currentTimeMs(): number {
        if (!this.el) return 0;
        const off = this._window?.offsetMs ?? 0;
        return this.el.currentTime * 1000 + off;
    }

    coordinates(): { offsetMs: number } {
        return { offsetMs: this._window?.offsetMs ?? 0 };
    }

    // -----------------------------------------------------------------------
    // Playback (file-absolute targets)
    // -----------------------------------------------------------------------

    /** Seek to a file-absolute position. Sync write — assigning to
     *  `audio.currentTime` is synchronous; the seeked event fires later
     *  but callers don't need to wait on that. Does NOT call play().
     *
     *  When the target is outside the currently-loaded window, the caller
     *  is expected to `loadCovering(...)` first; this method does NOT
     *  auto-load (that's a caller decision because pre-loads outside the
     *  port's knowledge are common, e.g. AudioRange's `start()`). */
    seek(fileMs: number): void {
        if (!this.el) return;
        const target = Math.max(0, this.toClipMs(fileMs));
        this.el.currentTime = target / 1000;
    }

    /** Seek + play. Sync — issues `play()` via `safePlay` (which swallows
     *  AbortError). The play promise itself is fire-and-forget. */
    seekAndPlay(fileMs: number): void {
        if (!this.el) return;
        this.seek(fileMs);
        // Restore gain ramp before playing; matches the legacy
        // `_seekAndPlay` ordering in `audio-range.ts`.
        uncutAudio(this.el);
        safePlay(this.el);
    }

    /** Resume play at the current position. Use for play/pause toggles where
     *  the AudioRange is still alive and the rAF chain is paused-but-ticking;
     *  no seek needed. */
    play(): void {
        if (!this.el) return;
        uncutAudio(this.el);
        safePlay(this.el);
    }

    pause(): void {
        if (this.el && !this.el.paused) this.el.pause();
    }

    /** Pause + Web Audio gain ramp to 0 to silence OS-buffered samples
     *  (mirrors `audio-range.ts::_pauseAndFlush`). */
    pauseAndFlush(): void {
        if (!this.el) return;
        cutAudio(this.el);
        if (!this.el.paused) this.el.pause();
    }

    /** Restore gain to 1. Called before resuming play after a flush. */
    uncut(): void {
        if (this.el) uncutAudio(this.el);
    }

    get paused(): boolean {
        return this.el?.paused ?? true;
    }

    get playbackRate(): number {
        return this.el?.playbackRate ?? 1;
    }

    setPlaybackRate(rate: number): void {
        if (this.el) this.el.playbackRate = rate;
    }

    // -----------------------------------------------------------------------
    // Events
    // -----------------------------------------------------------------------

    onLoad(cb: (w: LoadedWindow) => void): Unsub {
        this.loadSubs.add(cb);
        return () => this.loadSubs.delete(cb);
    }

    onPlay(cb: () => void): Unsub {
        this.playSubs.add(cb);
        return () => this.playSubs.delete(cb);
    }

    onPause(cb: () => void): Unsub {
        this.pauseSubs.add(cb);
        return () => this.pauseSubs.delete(cb);
    }

    onEnded(cb: () => void): Unsub {
        this.endedSubs.add(cb);
        return () => this.endedSubs.delete(cb);
    }

    /** Fires on the element's `timeupdate` event with file-absolute ms. */
    onTimeUpdate(cb: (fileMs: number) => void): Unsub {
        this.timeUpdateSubs.add(cb);
        return () => this.timeUpdateSubs.delete(cb);
    }

    onError(cb: (err: MediaError | null) => void): Unsub {
        this.errorSubs.add(cb);
        return () => this.errorSubs.delete(cb);
    }

    // -----------------------------------------------------------------------
    // Internal: src swap
    // -----------------------------------------------------------------------

    private _swapTo(url: string, win: LoadedWindow): LoadCoveringResult {
        if (!this.el) throw new Error('AudioPort._swapTo: no element');
        this._abortPendingLoad();
        const gen = ++this.loadGen;
        const promise = new Promise<void>((resolve, reject) => {
            const handler = (): void => {
                if (gen !== this.loadGen) return;
                this.el?.removeEventListener('canplay', handler);
                this.pendingCanplay = null;
                this.pendingReady = null;
                this._window = win;
                this._fanout(this.loadSubs, win);
                resolve();
            };
            this.pendingCanplay = handler;
            this.pendingReady = { resolve, reject };
            this.el!.addEventListener('canplay', handler, { once: true });
        });
        // Pin a no-op rejection handler so an internal abort (overlapping
        // load, setSource change, dispose) never trips Node's unhandled-
        // rejection warning when the caller hasn't yet attached its own
        // `.catch` / `await`. Promise subscribers are independent — any
        // external `await ready` still sees the rejection.
        promise.catch(() => {});
        this.el.src = url;
        this.el.load();
        return { ready: promise, swapped: true, window: win };
    }

    private _abortPendingLoad(): void {
        if (this.pendingCanplay && this.el) {
            this.el.removeEventListener('canplay', this.pendingCanplay);
        }
        this.pendingCanplay = null;
        if (this.pendingReady) {
            const r = this.pendingReady;
            this.pendingReady = null;
            const err = new DOMException('aborted by newer load', 'AbortError');
            r.reject(err);
        }
    }

    // -----------------------------------------------------------------------
    // Internal: DOM event re-emission
    // -----------------------------------------------------------------------

    private _attachDomListeners(el: HTMLAudioElement): void {
        const onPlay = (): void => this._fanout(this.playSubs);
        const onPause = (): void => this._fanout(this.pauseSubs);
        const onEnded = (): void => this._fanout(this.endedSubs);
        const onTimeUpdate = (): void => this._fanout(this.timeUpdateSubs, this.currentTimeMs());
        const onError = (): void => this._fanout(this.errorSubs, el.error);
        el.addEventListener('play', onPlay);
        el.addEventListener('pause', onPause);
        el.addEventListener('ended', onEnded);
        el.addEventListener('timeupdate', onTimeUpdate);
        el.addEventListener('error', onError);
        this.domListeners = [
            ['play', onPlay],
            ['pause', onPause],
            ['ended', onEnded],
            ['timeupdate', onTimeUpdate],
            ['error', onError],
        ];
    }

    private _detachDomListeners(): void {
        if (!this.el) { this.domListeners = []; return; }
        for (const [type, fn] of this.domListeners) {
            this.el.removeEventListener(type, fn);
        }
        this.domListeners = [];
    }

    private _fanout<T>(subs: Set<(arg: T) => void>, arg?: T): void {
        // Snapshot — subscribers may unsubscribe during their own callback.
        for (const fn of [...subs]) {
            try { fn(arg as T); }
            catch (e) {
                // Don't let a buggy subscriber take out the whole fanout.
                if (!isAbortError(e)) console.error('[AudioPort] subscriber threw', e);
            }
        }
    }
}
