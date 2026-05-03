/**
 * AudioRange — unified [startMs, endMs] window playback primitive.
 *
 * Owns ONE rAF loop and ONE boundary check per frame against a caller-supplied
 * range on a caller-supplied HTMLAudioElement. Pluggable boundary policy
 * (stop / loop / advance) handles the three behaviors the inspector needs:
 * single-segment play, trim/split loop preview, and autoplay advance.
 *
 * Composes existing infra:
 *   - `lib/utils/animation.ts::createAnimationLoop` — rAF wrapper.
 *   - `lib/utils/audio.ts::safePlay` / `audioSrcMatches`.
 *
 * No store imports — callers wire `onTick` / `onBoundary` to their own state.
 *
 * Caller contract: only ONE AudioRange may run on a given audio element at a
 * time. `enterEditMode` must `dispose()` the segments-main range before
 * starting an edit-preview range; `exitEditMode` does the reverse.
 */

import { createAnimationLoop, type AnimationLoop } from '../utils/animation';
import { audioSrcMatches, safePlay } from '../utils/audio';

export interface AudioRangeSpec {
    startMs: number;
    endMs: number;
    /** When set and !audioSrcMatches(audioEl.src, src), `start()` swaps the
     *  audio element's src and waits for `canplay` before seeking + playing. */
    src?: string | null;
}

export type RangePolicy =
    | { kind: 'stop' }
    | { kind: 'loop' }
    | {
          kind: 'advance';
          gapMs: number;
          nextRange: () => AudioRangeSpec | null;
      };

export type BoundaryReason = 'stop' | 'loop' | 'advance';

export interface BoundaryEvent {
    reason: BoundaryReason;
    /** Set on `advance` boundaries; mirrors the spec the primitive will load
     *  after the gap completes. */
    nextRange?: AudioRangeSpec;
}

export interface AudioRangeOptions {
    audioEl: HTMLAudioElement;
    range: AudioRangeSpec;
    policy: RangePolicy;
    onTick?: (timeMs: number) => void;
    onBoundary?: (ev: BoundaryEvent) => void;
    /** Called on every play() / resume so callers can apply the live playback
     *  rate without re-reading a store inside the primitive. */
    playbackRate?: () => number;
}

export class AudioRange {
    private readonly audioEl: HTMLAudioElement;
    private range: AudioRangeSpec;
    private policy: RangePolicy;
    private readonly onTick: ((ms: number) => void) | undefined;
    private readonly onBoundary: ((ev: BoundaryEvent) => void) | undefined;
    private readonly playbackRate: (() => number) | undefined;

    private loop: AnimationLoop;
    /** True between a loop seek-back and the first frame where `currentTime`
     *  drops below `endMs`. Prevents the boundary from firing twice on the
     *  same crossing if the audio decoder is laggy. Mirrors `_previewJustSeeked`
     *  in the legacy `play-range.ts:123`. */
    private seekedThisFrame = false;
    private gapTimeout: ReturnType<typeof setTimeout> | null = null;
    private canplayHandler: (() => void) | null = null;
    private disposed = false;

    constructor(opts: AudioRangeOptions) {
        this.audioEl = opts.audioEl;
        this.range = opts.range;
        this.policy = opts.policy;
        this.onTick = opts.onTick;
        this.onBoundary = opts.onBoundary;
        this.playbackRate = opts.playbackRate;
        this.loop = createAnimationLoop(() => this._frame());
    }

    // -----------------------------------------------------------------------
    // Public API
    // -----------------------------------------------------------------------

    start(): void {
        if (this.disposed) return;
        const { src } = this.range;
        if (src && !audioSrcMatches(this.audioEl.src, src)) {
            this._loadAndStart(this.range);
        } else {
            this._seekAndPlay(this.range.startMs);
            this.loop.start();
        }
    }

    /**
     * Start the rAF boundary-watcher loop WITHOUT seeking or calling play().
     * Use when the caller manages seek + play separately (e.g. an existing
     * AudioPlayer component already loaded the source and seeked to the verse
     * start) and only needs AudioRange's frame-precise boundary enforcement.
     *
     * Idempotent — calling while already attached is a no-op.
     */
    attach(): void {
        if (this.disposed) return;
        if (!this.loop.running()) this.loop.start();
    }

    stop(): void {
        this._cancelGap();
        this._detachCanplay();
        this.loop.stop();
        if (!this.audioEl.paused) this.audioEl.pause();
    }

    setRange(spec: AudioRangeSpec): void {
        this.range = spec;
        // A fresh range invalidates any pending advance gap and the
        // seeked-this-frame guard from a prior loop.
        this._cancelGap();
        this.seekedThisFrame = false;
    }

    setPolicy(p: RangePolicy): void {
        this.policy = p;
        this._cancelGap();
    }

    isRunning(): boolean {
        return !this.disposed && (this.loop.running() || this.gapTimeout !== null);
    }

    dispose(): void {
        this.disposed = true;
        this.stop();
    }

    // -----------------------------------------------------------------------
    // Internal: frame tick
    // -----------------------------------------------------------------------

    private _frame(): boolean | void {
        if (this.disposed) return false;
        // Pause-resilient: keep the rAF chain alive while the audio is paused
        // (post-seek transient, advance gap cooldown, external user pause).
        // We just don't tick onTick or check the boundary — those resume on unpause.
        if (this.audioEl.paused) return;

        const timeMs = this.audioEl.currentTime * 1000;

        // Seeked-this-frame guard: clear once currentTime has dropped below
        // endMs at least once after a loop seek-back.
        if (this.seekedThisFrame && timeMs < this.range.endMs) {
            this.seekedThisFrame = false;
        }

        if (timeMs >= this.range.endMs && !this.seekedThisFrame) {
            return this._handleBoundary();
        }

        this.onTick?.(timeMs);
        return;
    }

    private _handleBoundary(): boolean | void {
        switch (this.policy.kind) {
            case 'stop': {
                this._pauseAndFlush();
                this.onBoundary?.({ reason: 'stop' });
                return false;
            }
            case 'loop': {
                this.audioEl.currentTime = this.range.startMs / 1000;
                this.seekedThisFrame = true;
                this.onBoundary?.({ reason: 'loop' });
                return;
            }
            case 'advance': {
                const next = this.policy.nextRange();
                if (!next) {
                    this._pauseAndFlush();
                    this.onBoundary?.({ reason: 'stop' });
                    return false;
                }
                const gapMs = this.policy.gapMs;
                this._pauseAndFlush();
                this.onBoundary?.({ reason: 'advance', nextRange: next });
                this._scheduleAdvance(next, gapMs);
                return;
            }
        }
    }

    /** Pause the element AND clip `currentTime` to `range.endMs`.
     *
     * Browsers buffer ~50–200ms of decoded audio past the pause() call —
     * the OS audio device keeps draining the buffer before going silent.
     * Setting `currentTime` forces a seek which discards that buffer, so
     * the user does not hear audio content from positions past the segment
     * boundary. Without this, segment playback ends with an audible "tail"
     * of ~100–200ms of audio from the next part of the file. */
    private _pauseAndFlush(): void {
        this.audioEl.pause();
        this.audioEl.currentTime = this.range.endMs / 1000;
    }

    // -----------------------------------------------------------------------
    // Internal: advance gap
    // -----------------------------------------------------------------------

    private _scheduleAdvance(next: AudioRangeSpec, gapMs: number): void {
        this._cancelGap();
        this.gapTimeout = setTimeout(() => {
            this.gapTimeout = null;
            if (this.disposed) return;
            this.range = next;
            this.seekedThisFrame = false;
            if (next.src && !audioSrcMatches(this.audioEl.src, next.src)) {
                this._loadAndStart(next);
            } else {
                this._seekAndPlay(next.startMs);
                if (!this.loop.running()) this.loop.start();
            }
        }, gapMs);
    }

    private _cancelGap(): void {
        if (this.gapTimeout !== null) {
            clearTimeout(this.gapTimeout);
            this.gapTimeout = null;
        }
    }

    // -----------------------------------------------------------------------
    // Internal: src-swap + seek + play
    // -----------------------------------------------------------------------

    private _loadAndStart(spec: AudioRangeSpec): void {
        this._detachCanplay();
        const handler = (): void => {
            this.canplayHandler = null;
            if (this.disposed) return;
            this._seekAndPlay(spec.startMs);
            if (!this.loop.running()) this.loop.start();
        };
        this.canplayHandler = handler;
        this.audioEl.addEventListener('canplay', handler, { once: true });
        if (spec.src != null) this.audioEl.src = spec.src;
        this.audioEl.load();
    }

    private _detachCanplay(): void {
        if (this.canplayHandler) {
            this.audioEl.removeEventListener('canplay', this.canplayHandler);
            this.canplayHandler = null;
        }
    }

    private _seekAndPlay(startMs: number): void {
        this.audioEl.currentTime = startMs / 1000;
        if (this.playbackRate) this.audioEl.playbackRate = this.playbackRate();
        safePlay(this.audioEl);
    }
}
