import { describe, it, expect } from 'vitest';

import { buildTimestampsRangeSpec } from '../range-spec';
import type { TsLoopTarget } from '../../stores/playback';
import type { TsLoadedVerse } from '../../stores/verse';

const loaded = (overrides: Partial<TsLoadedVerse> = {}): TsLoadedVerse => ({
    data: { ref: '1:1', words: [] } as unknown as TsLoadedVerse['data'],
    tsSegOffset: 0,
    tsSegEnd: 10,
    ...overrides,
});

const loop = (overrides: Partial<TsLoopTarget> = {}): TsLoopTarget => ({
    kind: 'word',
    startSec: 1.0,
    endSec: 2.0,
    wordIndex: 0,
    ...overrides,
});

describe('buildTimestampsRangeSpec', () => {
    it('returns null when no verse is loaded', () => {
        expect(buildTimestampsRangeSpec(null, null)).toBeNull();
        expect(buildTimestampsRangeSpec(null, loop())).toBeNull();
    });

    it('produces a loop policy when loopTarget is set, in absolute ms with offset applied', () => {
        const spec = buildTimestampsRangeSpec(loaded({ tsSegOffset: 5 }), loop({ startSec: 1, endSec: 2 }));
        expect(spec).not.toBeNull();
        expect(spec!.policy.kind).toBe('loop');
        expect(spec!.range.startMs).toBeCloseTo(6000, 5);
        expect(spec!.range.endMs).toBeCloseTo(7000, 5);
    });

    it('produces a stop policy clamped to tsSegEnd when no loopTarget', () => {
        const spec = buildTimestampsRangeSpec(loaded({ tsSegEnd: 12.5 }), null);
        expect(spec).not.toBeNull();
        expect(spec!.policy.kind).toBe('stop');
        expect(spec!.range.startMs).toBe(0);
        expect(spec!.range.endMs).toBeCloseTo(12500, 5);
    });

    it('returns +Infinity endMs when tsSegEnd <= 0 so the rAF still runs without a boundary', () => {
        const spec = buildTimestampsRangeSpec(loaded({ tsSegEnd: 0 }), null);
        expect(spec!.policy.kind).toBe('stop');
        expect(spec!.range.endMs).toBe(Number.POSITIVE_INFINITY);

        const spec2 = buildTimestampsRangeSpec(loaded({ tsSegEnd: -1 }), null);
        expect(spec2!.range.endMs).toBe(Number.POSITIVE_INFINITY);
    });

    it('prefers loop over auto-advance when both are configured', () => {
        // loopTarget is mutually exclusive with autoMode by store contract,
        // but defensively the helper picks loop.
        const spec = buildTimestampsRangeSpec(loaded({ tsSegEnd: 12 }), loop({ startSec: 1, endSec: 2 }));
        expect(spec!.policy.kind).toBe('loop');
        expect(spec!.range.endMs).toBeCloseTo(2000, 5);
    });
});
