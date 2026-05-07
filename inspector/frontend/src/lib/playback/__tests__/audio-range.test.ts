/**
 * AudioRange — unified [startMs, endMs] window playback primitive.
 *
 * Covers the 8 cases enumerated in plan-the-e2e-impl-quizzical-cook.md §4b:
 * boundary precision, stop/loop/advance policies, dynamic range, src swap,
 * pause-resilient loop, dispose.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { cutAudio, uncutAudio } from '../audio-graph';
import { AudioRange, type AudioRangeSpec, type RangePolicy } from '../audio-range';
import { type AudioStub, installRafMock, makeAudioStub, type RafMock } from './raf-harness';

// Mock audio-graph so we can assert when AudioRange invokes the kill-switch
// and gain-restore primitives. happy-dom has no Web Audio, so the real
// module's getAudioGraph would no-op anyway — replacing with spies costs
// nothing for the existing tests and lets the regression test below assert.
vi.mock('../audio-graph', () => ({
    cutAudio: vi.fn(),
    uncutAudio: vi.fn(),
    getAudioGraph: vi.fn(() => null),
    _getCtx: vi.fn(() => null),
}));

let raf: RafMock;
let audio: AudioStub;

beforeEach(() => {
    raf = installRafMock();
    audio = makeAudioStub({ src: 'http://x/seg.mp3', readyState: 4 });
    vi.mocked(cutAudio).mockClear();
    vi.mocked(uncutAudio).mockClear();
});

afterEach(() => {
    raf.restore();
    vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildRange(opts: {
    range?: AudioRangeSpec;
    policy?: RangePolicy;
    onTick?: (ms: number) => void;
    onBoundary?: (ev: { reason: string; nextRange?: AudioRangeSpec }) => void;
}) {
    return new AudioRange({
        audioEl: audio as unknown as HTMLAudioElement,
        range: opts.range ?? { startMs: 0, endMs: 1000 },
        policy: opts.policy ?? { kind: 'stop' },
        onTick: opts.onTick,
        onBoundary: opts.onBoundary,
    });
}

// ---------------------------------------------------------------------------
// 1. Boundary precision
// ---------------------------------------------------------------------------

describe('AudioRange — boundary precision', () => {
    it('does NOT fire boundary while currentTime < endMs', () => {
        const onBoundary = vi.fn();
        const r = buildRange({ onBoundary });
        r.start();

        audio.currentTime = 0.999;
        raf.flushFrames(1);

        expect(onBoundary).not.toHaveBeenCalled();
    });

    it('fires boundary on the first frame after currentTime >= endMs', () => {
        const onBoundary = vi.fn();
        const r = buildRange({ onBoundary });
        r.start();

        audio.currentTime = 0.999;
        raf.flushFrames(1);
        audio.currentTime = 1.001;
        raf.flushFrames(1);

        expect(onBoundary).toHaveBeenCalledTimes(1);
        expect(onBoundary.mock.calls[0]?.[0]).toMatchObject({ reason: 'stop' });
    });
});

// ---------------------------------------------------------------------------
// 2. Policy: stop
// ---------------------------------------------------------------------------

describe('AudioRange — policy stop', () => {
    it('pauses audio and self-cancels the rAF loop on boundary', () => {
        const onTick = vi.fn();
        const onBoundary = vi.fn();
        const r = buildRange({ policy: { kind: 'stop' }, onTick, onBoundary });
        r.start();

        // Run a few frames inside the range — onTick fires.
        audio.currentTime = 0.5;
        raf.flushFrames(3);
        const tickCountInside = onTick.mock.calls.length;
        expect(tickCountInside).toBeGreaterThan(0);

        // Cross the boundary — pause + onBoundary once.
        audio.currentTime = 1.001;
        raf.flushFrames(1);
        expect(audio.pause).toHaveBeenCalledTimes(1);
        expect(onBoundary).toHaveBeenCalledTimes(1);

        // Subsequent frames produce no further activity (loop self-cancelled).
        raf.flushFrames(5);
        expect(onTick.mock.calls.length).toBe(tickCountInside);
        expect(onBoundary).toHaveBeenCalledTimes(1);
        expect(r.isRunning()).toBe(false);
    });

    it('clips currentTime to endMs after pause to flush the audio output buffer', () => {
        // Browsers buffer ~50–200ms of audio output past pause(). Setting
        // currentTime forces a seek which clears that buffer, eliminating
        // the trailing audible "extra sound" past the segment boundary.
        const r = buildRange({ range: { startMs: 0, endMs: 1000 }, policy: { kind: 'stop' } });
        r.start();

        audio.currentTime = 1.05;  // already a hair past endMs (rAF granularity)
        raf.flushFrames(1);

        expect(audio.pause).toHaveBeenCalled();
        expect(audio.currentTime).toBeCloseTo(1.0, 5);  // clipped exactly to endMs
    });
});

// ---------------------------------------------------------------------------
// 3. Policy: loop
// ---------------------------------------------------------------------------

describe('AudioRange — policy loop', () => {
    it('seeks to startMs without pausing and reports boundary as loop', () => {
        const onBoundary = vi.fn();
        const r = buildRange({
            range: { startMs: 200, endMs: 1000 },
            policy: { kind: 'loop' },
            onBoundary,
        });
        r.start();

        audio.currentTime = 1.001;
        raf.flushFrames(1);

        expect(audio.pause).not.toHaveBeenCalled();
        expect(audio.currentTime).toBeCloseTo(0.2, 5);
        expect(onBoundary).toHaveBeenCalledTimes(1);
        expect(onBoundary.mock.calls[0]?.[0]).toMatchObject({ reason: 'loop' });
        expect(r.isRunning()).toBe(true);
    });

    it('does not re-fire boundary on the same frame the seek-back happens', () => {
        // Even if the test forcibly re-pushes currentTime past endMs on the very
        // next frame (simulating a decoder lag), the seeked-this-frame guard
        // prevents a double-fire until currentTime drops below endMs at least once.
        const onBoundary = vi.fn();
        const r = buildRange({
            range: { startMs: 0, endMs: 1000 },
            policy: { kind: 'loop' },
            onBoundary,
        });
        r.start();

        audio.currentTime = 1.001;
        raf.flushFrames(1);  // first loop fires
        expect(onBoundary).toHaveBeenCalledTimes(1);

        // Pretend the seek didn't take effect yet (decoder lag simulation).
        audio.currentTime = 1.001;
        raf.flushFrames(1);
        expect(onBoundary).toHaveBeenCalledTimes(1);  // guard held

        // Once currentTime drops below endMs, the guard clears and the next
        // crossing fires again.
        audio.currentTime = 0.5;
        raf.flushFrames(1);
        audio.currentTime = 1.001;
        raf.flushFrames(1);
        expect(onBoundary).toHaveBeenCalledTimes(2);
    });
});

// ---------------------------------------------------------------------------
// 4. Policy: advance with gapMs > 0
// ---------------------------------------------------------------------------

describe('AudioRange — policy advance', () => {
    it('pauses, schedules a gap, then resumes at nextRange.startMs', () => {
        vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
        const onBoundary = vi.fn();
        const next: AudioRangeSpec = { startMs: 2000, endMs: 3000 };
        const r = buildRange({
            range: { startMs: 0, endMs: 1000 },
            policy: { kind: 'advance', gapMs: 200, nextRange: () => next },
            onBoundary,
        });
        r.start();

        audio.currentTime = 1.001;
        raf.flushFrames(1);

        expect(audio.pause).toHaveBeenCalledTimes(1);
        expect(onBoundary).toHaveBeenCalledTimes(1);
        expect(onBoundary.mock.calls[0]?.[0]).toMatchObject({
            reason: 'advance',
            nextRange: next,
        });
        // play() not called yet — still inside the gap.
        const playCallsBeforeGap = audio.play.mock.calls.length;

        vi.advanceTimersByTime(200);

        expect(audio.currentTime).toBeCloseTo(2.0, 5);
        expect(audio.play.mock.calls.length).toBeGreaterThan(playCallsBeforeGap);
        expect(r.isRunning()).toBe(true);
    });

    it('falls back to stop when nextRange returns null', () => {
        vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
        const onBoundary = vi.fn();
        const r = buildRange({
            policy: { kind: 'advance', gapMs: 100, nextRange: () => null },
            onBoundary,
        });
        r.start();

        audio.currentTime = 1.001;
        raf.flushFrames(1);
        vi.advanceTimersByTime(100);

        // Boundary fired once with reason advance + nextRange undefined fallback,
        // OR once with reason stop. Either way, we end up paused and not running.
        expect(audio.paused).toBe(true);
        expect(r.isRunning()).toBe(false);
    });

    it('clips currentTime to endMs at the gap-pause to flush the output buffer', () => {
        vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
        const next: AudioRangeSpec = { startMs: 2000, endMs: 3000 };
        const r = buildRange({
            range: { startMs: 0, endMs: 1000 },
            policy: { kind: 'advance', gapMs: 200, nextRange: () => next },
        });
        r.start();

        audio.currentTime = 1.05;
        raf.flushFrames(1);

        // Pause + buffer flush happen synchronously at the boundary.
        expect(audio.pause).toHaveBeenCalled();
        expect(audio.currentTime).toBeCloseTo(1.0, 5);
    });

    it('cancels pending gap timer when stop() is called mid-gap', () => {
        vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
        const next: AudioRangeSpec = { startMs: 2000, endMs: 3000 };
        const r = buildRange({
            policy: { kind: 'advance', gapMs: 200, nextRange: () => next },
        });
        r.start();

        audio.currentTime = 1.001;
        raf.flushFrames(1);
        // Inside the gap now.
        r.stop();
        const playCallsAtStop = audio.play.mock.calls.length;
        vi.advanceTimersByTime(500);

        expect(audio.play.mock.calls.length).toBe(playCallsAtStop);
        expect(r.isRunning()).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// 5. Dynamic range mid-play
// ---------------------------------------------------------------------------

describe('AudioRange — setRange', () => {
    it('applies new range bounds on the next frame', () => {
        const onBoundary = vi.fn();
        const r = buildRange({
            range: { startMs: 0, endMs: 1000 },
            onBoundary,
        });
        r.start();

        audio.currentTime = 0.6;
        raf.flushFrames(1);
        expect(onBoundary).not.toHaveBeenCalled();

        r.setRange({ startMs: 0, endMs: 500 });
        raf.flushFrames(1);

        expect(onBoundary).toHaveBeenCalledTimes(1);
    });

    it('lifts a pending kill-switch gain ramp from a prior _pauseAndFlush', () => {
        // Repro for the Timestamps-tab silent-audio bug after auto-next:
        // the prior verse's `stop` boundary calls cutAudio → GainNode = 0;
        // when AudioPlayer.load() drives the next play(), AudioRange's
        // internal _seekAndPlay (which would call uncutAudio) never runs.
        // setRange must lift the ramp so the next play() isn't silent.
        const r = buildRange({
            range: { startMs: 0, endMs: 1000 },
            policy: { kind: 'stop' },
        });
        r.start();

        // Cross the boundary — _pauseAndFlush → cutAudio fires once.
        audio.currentTime = 1.001;
        raf.flushFrames(1);
        expect(vi.mocked(cutAudio)).toHaveBeenCalledTimes(1);

        // Reset the uncut counter so we can isolate setRange's effect from
        // the uncut() that fires inside r.start()'s initial _seekAndPlay.
        vi.mocked(uncutAudio).mockClear();

        // External orchestrator (TimestampsTab) loads the next verse and
        // re-specs the range. The ramp must be lifted before play() lands.
        r.setRange({ startMs: 0, endMs: 2000 });
        expect(vi.mocked(uncutAudio)).toHaveBeenCalledTimes(1);
        expect(vi.mocked(uncutAudio)).toHaveBeenCalledWith(audio);
    });
});

// ---------------------------------------------------------------------------
// 6. src swap during start
// ---------------------------------------------------------------------------

describe('AudioRange — src swap', () => {
    it('attaches canplay listener and defers play() until the event fires', () => {
        audio.src = 'http://x/old.mp3';
        const onTick = vi.fn();
        const r = buildRange({
            range: { startMs: 0, endMs: 1000, src: 'http://x/new.mp3' },
            onTick,
        });
        r.start();

        // load() called, src updated, a canplay listener attached, play NOT yet.
        expect(audio.load).toHaveBeenCalled();
        expect(audio.src).toBe('http://x/new.mp3');
        expect(audio.play).not.toHaveBeenCalled();
        expect(audio._listeners.get('canplay')?.size ?? 0).toBeGreaterThan(0);

        // Fire canplay synthetically — now seek + play happen.
        audio._fireEvent('canplay');
        expect(audio.currentTime).toBeCloseTo(0, 5);
        expect(audio.play).toHaveBeenCalledTimes(1);
    });

    it('plays immediately when src already matches', () => {
        audio.src = 'http://x/seg.mp3';
        const r = buildRange({
            range: { startMs: 100, endMs: 1000, src: 'http://x/seg.mp3' },
        });
        r.start();

        expect(audio.load).not.toHaveBeenCalled();
        expect(audio.play).toHaveBeenCalledTimes(1);
        expect(audio.currentTime).toBeCloseTo(0.1, 5);
    });
});

// ---------------------------------------------------------------------------
// 7. Pause-resilient loop
// ---------------------------------------------------------------------------

describe('AudioRange — pause-resilient loop', () => {
    it('keeps rAF alive while audio is externally paused; resumes onTick on unpause', () => {
        const onTick = vi.fn();
        const r = buildRange({ onTick });
        r.start();

        audio.currentTime = 0.1;
        raf.flushFrames(1);
        const ticksAfterFirst = onTick.mock.calls.length;
        expect(ticksAfterFirst).toBeGreaterThan(0);

        // External pause (e.g. user click). Frame loop must keep ticking
        // (rAF queue stays non-empty) but onTick should not fire.
        audio.paused = true;
        raf.flushFrames(3);
        expect(onTick.mock.calls.length).toBe(ticksAfterFirst);
        expect(r.isRunning()).toBe(true);
        expect(raf.queueLength()).toBeGreaterThan(0);

        // Unpause — onTick fires again.
        audio.paused = false;
        audio.currentTime = 0.2;
        raf.flushFrames(1);
        expect(onTick.mock.calls.length).toBe(ticksAfterFirst + 1);
    });
});

// ---------------------------------------------------------------------------
// 8a. attach (no seek, no play)
// ---------------------------------------------------------------------------

describe('AudioRange — attach', () => {
    it('starts the rAF loop without seeking or calling play()', () => {
        audio.currentTime = 4.2;       // pretend caller already seeked
        audio.paused = false;          // pretend caller already started playback
        const onTick = vi.fn();
        const r = buildRange({ range: { startMs: 1000, endMs: 5000 }, onTick });
        r.attach();

        expect(audio.play).not.toHaveBeenCalled();
        expect(audio.currentTime).toBeCloseTo(4.2, 5);  // not reseeked

        raf.flushFrames(1);
        expect(onTick).toHaveBeenCalledTimes(1);
        expect(onTick.mock.calls[0]?.[0]).toBeCloseTo(4200, 5);
    });

    it('still enforces boundary at frame precision under loop policy', () => {
        audio.currentTime = 0;
        audio.paused = false;
        const onBoundary = vi.fn();
        const r = buildRange({
            range: { startMs: 200, endMs: 1000 },
            policy: { kind: 'loop' },
            onBoundary,
        });
        r.attach();

        audio.currentTime = 1.001;
        raf.flushFrames(1);
        expect(audio.currentTime).toBeCloseTo(0.2, 5);
        expect(onBoundary).toHaveBeenCalledTimes(1);
    });
});

// ---------------------------------------------------------------------------
// 8. dispose
// ---------------------------------------------------------------------------

describe('AudioRange — dispose', () => {
    it('detaches canplay listener and cancels pending advance timer', () => {
        vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
        audio.src = 'http://x/old.mp3';
        const r = buildRange({
            range: { startMs: 0, endMs: 1000, src: 'http://x/new.mp3' },
            policy: { kind: 'advance', gapMs: 500, nextRange: () => ({ startMs: 0, endMs: 100 }) },
        });
        r.start();

        // canplay listener attached pre-load.
        expect(audio._listeners.get('canplay')?.size ?? 0).toBeGreaterThan(0);

        r.dispose();

        expect(audio._listeners.get('canplay')?.size ?? 0).toBe(0);
        expect(r.isRunning()).toBe(false);

        // Advancing fake timers past any plausible gap window must not start playback.
        const playCalls = audio.play.mock.calls.length;
        vi.advanceTimersByTime(10_000);
        expect(audio.play.mock.calls.length).toBe(playCalls);
    });
});
