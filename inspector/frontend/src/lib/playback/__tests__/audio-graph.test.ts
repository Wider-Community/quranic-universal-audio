/**
 * Web Audio kill-switch — sample-accurate gain ramp before the OS sink.
 *
 * happy-dom does not implement Web Audio. Each test installs a minimal
 * fake AudioContext that records GainParam scheduling.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

interface ScheduledOp {
    kind: 'set' | 'ramp' | 'cancel';
    t: number;
    v?: number;
}

class FakeGainParam {
    value = 1;
    scheduled: ScheduledOp[] = [];
    cancelScheduledValues(t: number): void {
        this.scheduled.push({ kind: 'cancel', t });
    }
    setValueAtTime(v: number, t: number): void {
        this.scheduled.push({ kind: 'set', t, v });
        this.value = v;
    }
    linearRampToValueAtTime(v: number, t: number): void {
        this.scheduled.push({ kind: 'ramp', t, v });
        this.value = v;
    }
}

const _createMediaElementSource = vi.fn();
const _createGain = vi.fn();
const _ctxResume = vi.fn(() => Promise.resolve());

class FakeAudioContext {
    currentTime = 0;
    state: 'suspended' | 'running' = 'running';
    destination = { _name: 'destination' };
    createMediaElementSource(el: HTMLMediaElement): { connect: (n: unknown) => unknown } {
        _createMediaElementSource(el);
        return { connect: (n: unknown) => n };
    }
    createGain(): { gain: FakeGainParam; connect: (n: unknown) => unknown } {
        const gain = new FakeGainParam();
        _createGain(gain);
        return { gain, connect: (n: unknown) => n };
    }
    resume(): Promise<void> {
        this.state = 'running';
        return _ctxResume();
    }
}

const originalAudioContext = (globalThis as { AudioContext?: typeof AudioContext }).AudioContext;

beforeEach(() => {
    vi.resetModules();
    _createMediaElementSource.mockClear();
    _createGain.mockClear();
    _ctxResume.mockClear();
    (globalThis as { AudioContext: typeof AudioContext }).AudioContext =
        FakeAudioContext as unknown as typeof AudioContext;
});

afterEach(() => {
    if (originalAudioContext) {
        (globalThis as { AudioContext: typeof AudioContext }).AudioContext = originalAudioContext;
    } else {
        delete (globalThis as { AudioContext?: typeof AudioContext }).AudioContext;
    }
});

function fakeAudio(): HTMLAudioElement {
    return { _tag: 'audio' } as unknown as HTMLAudioElement;
}

describe('audio-graph', () => {
    it('cutAudio schedules setValueAtTime + linearRamp(0, +5ms) and cancels prior scheduled values', async () => {
        const { cutAudio, getAudioGraph } = await import('../audio-graph');
        const el = fakeAudio();
        cutAudio(el);
        const graph = getAudioGraph(el)!;
        const ops = (graph.gain.gain as unknown as FakeGainParam).scheduled;

        expect(ops[0]).toEqual({ kind: 'cancel', t: 0 });
        expect(ops[1]).toMatchObject({ kind: 'set', t: 0 });
        expect(ops[2]).toMatchObject({ kind: 'ramp', v: 0 });
        const ramp = ops[2]!;
        expect(ramp.t).toBeCloseTo(0.005, 6);
    });

    it('uncutAudio schedules a ramp back to 1 over 5 ms', async () => {
        const { uncutAudio, getAudioGraph } = await import('../audio-graph');
        const el = fakeAudio();
        uncutAudio(el);
        const ops = (getAudioGraph(el)!.gain.gain as unknown as FakeGainParam).scheduled;
        const ramp = ops.find((o) => o.kind === 'ramp');
        expect(ramp).toMatchObject({ kind: 'ramp', v: 1 });
        expect(ramp!.t).toBeCloseTo(0.005, 6);
    });

    it('getAudioGraph is idempotent — repeated calls reuse one MediaElementAudioSourceNode per element', async () => {
        const { getAudioGraph } = await import('../audio-graph');
        const el = fakeAudio();
        const a = getAudioGraph(el);
        const b = getAudioGraph(el);
        const c = getAudioGraph(el);

        expect(a).toBe(b);
        expect(b).toBe(c);
        expect(_createMediaElementSource).toHaveBeenCalledTimes(1);
        expect(_createGain).toHaveBeenCalledTimes(1);
    });

    it('two different elements get independent graphs', async () => {
        const { getAudioGraph } = await import('../audio-graph');
        const el1 = fakeAudio();
        const el2 = fakeAudio();

        const g1 = getAudioGraph(el1)!;
        const g2 = getAudioGraph(el2)!;

        expect(g1).not.toBe(g2);
        expect(g1.gain).not.toBe(g2.gain);
        expect(_createMediaElementSource).toHaveBeenCalledTimes(2);
    });

    it('cutAudio/uncutAudio call ctx.resume() if the context is suspended', async () => {
        // Override the FakeAudioContext to start suspended.
        class SuspendedCtx extends FakeAudioContext {
            override state: 'suspended' | 'running' = 'suspended';
        }
        (globalThis as { AudioContext: typeof AudioContext }).AudioContext =
            SuspendedCtx as unknown as typeof AudioContext;

        const { cutAudio } = await import('../audio-graph');
        cutAudio(fakeAudio());
        expect(_ctxResume).toHaveBeenCalled();
    });
});

class LatencyCtx extends FakeAudioContext {
    baseLatency = 0.01;
    outputLatency = 0.04;
}

describe('output latency / displayTimeMs', () => {
    it('getOutputLatencyMs returns (baseLatency + outputLatency) * 1000', async () => {
        (globalThis as { AudioContext: typeof AudioContext }).AudioContext =
            LatencyCtx as unknown as typeof AudioContext;
        const { getOutputLatencyMs } = await import('../audio-graph');
        expect(getOutputLatencyMs()).toBeCloseTo(50, 6);
    });

    it('displayTimeMs subtracts the output latency from the media clock', async () => {
        (globalThis as { AudioContext: typeof AudioContext }).AudioContext =
            LatencyCtx as unknown as typeof AudioContext;
        const { displayTimeMs } = await import('../audio-graph');
        expect(displayTimeMs(1000)).toBeCloseTo(950, 6);
    });

    it('displayTimeMs clamps to 0 when latency exceeds the media position', async () => {
        (globalThis as { AudioContext: typeof AudioContext }).AudioContext =
            LatencyCtx as unknown as typeof AudioContext;
        const { displayTimeMs } = await import('../audio-graph');
        expect(displayTimeMs(10)).toBe(0);
    });

    it('displayTimeMs is identity (latency 0) when no AudioContext is available', async () => {
        delete (globalThis as { AudioContext?: typeof AudioContext }).AudioContext;
        const { displayTimeMs, getOutputLatencyMs } = await import('../audio-graph');
        expect(getOutputLatencyMs()).toBe(0);
        expect(displayTimeMs(1234)).toBe(1234);
    });

    it('getOutputLatencyMs falls back to the last non-zero reading when the live value drops to 0', async () => {
        // A browser reports outputLatency as 0 while the ctx is suspended / on
        // the first play before the graph is in the signal path. The cached
        // last-good value must survive that window so the compensation (and the
        // cursor/footer it drives) doesn't snap back to uncompensated.
        (globalThis as { AudioContext: typeof AudioContext }).AudioContext =
            LatencyCtx as unknown as typeof AudioContext;
        const { getOutputLatencyMs, _getCtx } = await import('../audio-graph');
        expect(getOutputLatencyMs()).toBeCloseTo(50, 6);
        const ctx = _getCtx() as unknown as { baseLatency: number; outputLatency: number };
        ctx.baseLatency = 0;
        ctx.outputLatency = 0;
        expect(getOutputLatencyMs()).toBeCloseTo(50, 6);
    });
});
