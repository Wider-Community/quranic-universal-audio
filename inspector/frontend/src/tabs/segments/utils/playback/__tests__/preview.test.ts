/**
 * PreviewPlaybackContext — toggle / switch / dispose semantics.
 *
 * Verifies the SavePreview / HistoryPanel playback wrapper without booting
 * the full segments tab. Reuses the rAF harness + audio stub from the
 * audio-range tests; mocks the segments-tab modules preview.ts pulls in.
 */

import { writable } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { type AudioStub, installRafMock, makeAudioStub, type RafMock } from '../../../../../lib/playback/__tests__/raf-harness';

vi.mock('../../../../../lib/utils/peaks-fetch', () => ({
    fetchSegmentPeaks: vi.fn(async () => null),
}));
vi.mock('../../../stores/chapter', () => ({
    selectedReciter: writable<string | null>('test-reciter'),
    reciterVbrChapters: writable<Set<number>>(new Set()),
    // Empty array means `_isCurrentReciterBySurah()` returns false, so the
    // `cbrSrc === audio_url` raw-URL assertions in these tests hold.
    segAllReciters: writable<Array<{ slug: string; audio_source?: string }>>([]),
}));
vi.mock('../../../stores/playback', () => ({
    playbackSpeed: writable<number>(1),
}));
vi.mock('../../waveform/draw-seg', () => ({
    drawSegPlayhead: vi.fn(),
}));
vi.mock('../../waveform/peaks-cache', () => ({
    _findCoveringPeaks: vi.fn(() => ({ peaks: [[-1, 1]], duration_ms: 1000, start_ms: 0 })),
}));
vi.mock('../../waveform/utils', () => ({
    indexSegPeaksBulk: vi.fn(),
    redrawPeaksWaveforms: vi.fn(),
}));

import { reciterVbrChapters } from '../../../stores/chapter';
import { createPreviewPlaybackContext } from '../preview';

let raf: RafMock;
let audio: AudioStub;
let canvas: HTMLCanvasElement;

beforeEach(() => {
    raf = installRafMock();
    audio = makeAudioStub({ src: 'http://x/audio.mp3', readyState: 4 });
    canvas = document.createElement('canvas');
    canvas.width = 200;
    canvas.height = 50;
    reciterVbrChapters.set(new Set());
});

afterEach(() => {
    raf.restore();
    vi.clearAllMocks();
});

describe('PreviewPlaybackContext — toggle from idle', () => {
    it('plays the registered row and sets activeSeg to its uid', () => {
        const ctx = createPreviewPlaybackContext();
        ctx.attachAudioEl(audio as unknown as HTMLAudioElement);
        ctx.registerRow('row-1', canvas, 'http://x/audio.mp3', 1000, 2000);

        let active: { uid: string } | null = null;
        const unsub = ctx.activeSeg.subscribe((v) => { active = v; });

        ctx.toggle('row-1');
        expect(audio.play).toHaveBeenCalledTimes(1);
        expect(active).toEqual({ uid: 'row-1' });
        unsub();
        ctx.dispose();
    });

    it('routes rows whose own chapter is VBR through the segment clip endpoint', async () => {
        reciterVbrChapters.set(new Set([2]));
        const ctx = createPreviewPlaybackContext();
        ctx.attachAudioEl(audio as unknown as HTMLAudioElement);
        ctx.registerRow('row-1', canvas, 'http://x/audio.mp3', 1000, 2000, undefined, undefined, undefined, 2);

        ctx.toggle('row-1');
        expect(audio.src).toContain('/api/seg/segment-clip/test-reciter');
        expect(audio.src).toContain('start_ms=1000');
        expect(audio.play).toHaveBeenCalledTimes(0);

        audio._fireEvent('canplay');
        await Promise.resolve();

        expect(audio.play).toHaveBeenCalledTimes(1);
        expect(audio.currentTime).toBeCloseTo(0, 5);
        ctx.dispose();
    });
});

describe('PreviewPlaybackContext — toggle on the same row', () => {
    it('pauses while playing, resumes after pause', () => {
        const ctx = createPreviewPlaybackContext();
        ctx.attachAudioEl(audio as unknown as HTMLAudioElement);
        ctx.registerRow('row-1', canvas, 'http://x/audio.mp3', 1000, 2000);

        ctx.toggle('row-1');
        expect(audio.play).toHaveBeenCalledTimes(1);
        expect(audio.paused).toBe(false);

        ctx.toggle('row-1');
        expect(audio.pause).toHaveBeenCalled();
        expect(audio.paused).toBe(true);

        ctx.toggle('row-1');
        expect(audio.play).toHaveBeenCalledTimes(2);
        expect(audio.paused).toBe(false);
        ctx.dispose();
    });
});

describe('PreviewPlaybackContext — switch rows', () => {
    it('disposes prior range and starts the new row when a different uid toggles', () => {
        const ctx = createPreviewPlaybackContext();
        ctx.attachAudioEl(audio as unknown as HTMLAudioElement);
        const c2 = document.createElement('canvas');
        c2.width = 200; c2.height = 50;
        ctx.registerRow('row-1', canvas, 'http://x/audio.mp3', 1000, 2000);
        ctx.registerRow('row-2', c2, 'http://x/audio.mp3', 3000, 4000);

        let active: { uid: string } | null = null;
        const unsub = ctx.activeSeg.subscribe((v) => { active = v; });

        ctx.toggle('row-1');
        expect(active).toEqual({ uid: 'row-1' });

        ctx.toggle('row-2');
        // Switching disposes the prior range (which pauses) then plays again.
        expect(audio.pause).toHaveBeenCalled();
        expect(audio.play).toHaveBeenCalledTimes(2);
        expect(active).toEqual({ uid: 'row-2' });
        unsub();
        ctx.dispose();
    });
});

describe('PreviewPlaybackContext — boundary stop clears active', () => {
    it('clears activeSeg when the AudioRange boundary fires (currentTime >= endMs)', () => {
        const ctx = createPreviewPlaybackContext();
        ctx.attachAudioEl(audio as unknown as HTMLAudioElement);
        ctx.registerRow('row-1', canvas, 'http://x/audio.mp3', 1000, 2000);

        let active: { uid: string } | null = null;
        const unsub = ctx.activeSeg.subscribe((v) => { active = v; });

        ctx.toggle('row-1');
        expect(active).toEqual({ uid: 'row-1' });

        // Drive the audio past the end-of-range and flush a frame.
        audio.currentTime = 2.001;
        raf.flushFrames(1);

        expect(active).toBeNull();
        unsub();
        ctx.dispose();
    });
});

describe('PreviewPlaybackContext — dispose', () => {
    it('clears state, removes audio listeners, and is safe to call twice', () => {
        const ctx = createPreviewPlaybackContext();
        ctx.attachAudioEl(audio as unknown as HTMLAudioElement);
        ctx.registerRow('row-1', canvas, 'http://x/audio.mp3', 1000, 2000);
        ctx.toggle('row-1');

        let active: { uid: string } | null = null;
        const unsub = ctx.activeSeg.subscribe((v) => { active = v; });

        ctx.dispose();
        expect(active).toBeNull();
        expect(audio.removeEventListener).toHaveBeenCalled();

        // Calling toggle after dispose is a no-op (audioEl is null).
        ctx.toggle('row-1');
        // play() calls so far: just the initial one before dispose.
        expect(audio.play).toHaveBeenCalledTimes(1);

        // Double-dispose doesn't throw.
        expect(() => ctx.dispose()).not.toThrow();
        unsub();
    });
});

describe('PreviewPlaybackContext — deregister active row', () => {
    it('stops playback if the currently-playing row is deregistered', () => {
        const ctx = createPreviewPlaybackContext();
        ctx.attachAudioEl(audio as unknown as HTMLAudioElement);
        ctx.registerRow('row-1', canvas, 'http://x/audio.mp3', 1000, 2000);

        let active: { uid: string } | null = null;
        const unsub = ctx.activeSeg.subscribe((v) => { active = v; });

        ctx.toggle('row-1');
        expect(active).toEqual({ uid: 'row-1' });

        const pauseCallsBefore = audio.pause.mock.calls.length;
        ctx.deregisterRow('row-1');
        expect(active).toBeNull();
        // The store-clear alone isn't enough; if a regression reordered
        // _stop() to clear state before disposing the range, the audio
        // element would keep playing. Pin the audible side effect.
        expect(audio.pause.mock.calls.length).toBeGreaterThan(pauseCallsBefore);
        unsub();
        ctx.dispose();
    });
});
