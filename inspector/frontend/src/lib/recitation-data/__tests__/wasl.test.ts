import { describe, expect, it } from 'vitest';

import { chapterOccasions } from '../occasions';
import type { SegmentEntry, TsShardWord } from '../../types/ts-client';
import {
    chapterWaslJunctions,
    isInWaslGroup,
    isPartialTake,
    isWaslBridge,
    takeWordRange,
    waslGroupOf,
} from '../wasl';

/** Minimal segment: words[lo..hi] (first/last word index), optional waṣl flag. */
function seg(ref: string, t0: number, t1: number, lo: number, hi: number, wasl?: boolean): SegmentEntry {
    const words: TsShardWord[] = [];
    for (let w = lo; w <= hi; w++) words.push([w, t0, t1, [], []]);
    const s: SegmentEntry = { ref, t: [t0, t1], words };
    if (wasl) s.wasl = true;
    return s;
}

describe('chapterOccasions — waṣl annotation', () => {
    it('back-stamps bridgesOutTo on the bridging occasion only', () => {
        // 14:1 (stop) | 14:2 | 14:1 (waṣl»14:2) | 14:2  — the showcase dynamic case.
        const occ = chapterOccasions([
            seg('14:1', 0, 1000, 1, 16),
            seg('14:2', 1000, 2000, 1, 9),
            seg('14:1', 2000, 3000, 13, 16, true),
            seg('14:2', 3000, 4000, 1, 9),
        ]);
        expect(occ.map((o) => o.ref)).toEqual(['14:1', '14:2', '14:1', '14:2']);
        expect(occ.map((o) => o.bridgesOutTo)).toEqual([null, null, '14:2', null]);
    });

    it('marks the boundary dynamic when the same pair also stops elsewhere', () => {
        const occ = chapterOccasions([
            seg('14:1', 0, 1000, 1, 16), // 14:1→14:2 crossed as a STOP here
            seg('14:2', 1000, 2000, 1, 9),
            seg('14:1', 2000, 3000, 13, 16, true), // …and as a WAṢL here
            seg('14:2', 3000, 4000, 1, 9),
        ]);
        expect(occ[2]!.bridgesDynamic).toBe(true);
    });

    it('keeps a pure chain static (every crossing is waṣl, never a stop)', () => {
        const occ = chapterOccasions([
            seg('20:25', 0, 1000, 1, 4, true),
            seg('20:26', 1000, 2000, 1, 5, true),
            seg('20:27', 2000, 3000, 1, 6, true),
            seg('20:28', 3000, 4000, 1, 7),
        ]);
        expect(occ.map((o) => o.bridgesOutTo)).toEqual(['20:26', '20:27', '20:28', null]);
        expect(occ.every((o) => !o.bridgesDynamic)).toBe(true);
    });

    it('no-ops on a v9 shard (no wasl flags)', () => {
        const occ = chapterOccasions([
            seg('2:5', 0, 1000, 1, 3),
            seg('2:6', 1000, 2000, 1, 4),
        ]);
        expect(occ.every((o) => o.bridgesOutTo === null && !o.bridgesDynamic)).toBe(true);
    });
});

describe('chapterWaslJunctions', () => {
    it('emits one junction per bridging occasion with word ranges + span', () => {
        const occ = chapterOccasions([
            seg('20:25', 100, 1000, 1, 4, true),
            seg('20:26', 1000, 2000, 1, 5, true),
            seg('20:27', 2000, 3000, 1, 6),
        ]);
        const j = chapterWaslJunctions(occ);
        expect(j.map((x) => `${x.fromRef}»${x.toRef}`)).toEqual(['20:25»20:26', '20:26»20:27']);
        expect(j[0]).toMatchObject({
            fromWords: [1, 4],
            toWords: [1, 5],
            leaveMs: 1000,
            enterMs: 1000,
            dynamic: false,
        });
    });

    it('returns [] when nothing bridges (v9)', () => {
        const occ = chapterOccasions([seg('2:5', 0, 1, 1, 3), seg('2:6', 1, 2, 1, 4)]);
        expect(chapterWaslJunctions(occ)).toEqual([]);
    });
});

describe('waslGroupOf / isInWaslGroup', () => {
    const chain = chapterOccasions([
        seg('20:25', 100, 1000, 1, 4, true),
        seg('20:26', 1000, 2000, 1, 5, true),
        seg('20:27', 2000, 3000, 1, 6, true),
        seg('20:28', 3000, 4200, 1, 7),
    ]);

    it('expands to the whole chain from any member', () => {
        const g = waslGroupOf(chain, 2); // focus on 20:27
        expect(g.refs).toEqual(['20:25', '20:26', '20:27', '20:28']);
        expect(g.fromIdx).toBe(0);
        expect(g.toIdx).toBe(3);
        expect(g.startMs).toBe(100);
        expect(g.endMs).toBe(4200);
    });

    it('flags every chain member as in-group', () => {
        expect([0, 1, 2, 3].every((i) => isInWaslGroup(chain, i))).toBe(true);
    });

    it('a standalone verse is its own group and not in-group', () => {
        const solo = chapterOccasions([seg('2:5', 0, 900, 1, 3), seg('2:6', 1000, 2000, 1, 4)]);
        expect(waslGroupOf(solo, 0).refs).toEqual(['2:5']);
        expect(isInWaslGroup(solo, 0)).toBe(false);
    });
});

describe('isPartialTake / takeWordRange / isWaslBridge', () => {
    it('takeWordRange reads first/last word index', () => {
        expect(takeWordRange(seg('30:4', 0, 1, 10, 12))).toEqual([10, 12]);
        expect(takeWordRange(seg('30:5', 0, 1, 1, 1))).toEqual([1, 1]);
    });

    it('isPartialTake flags trailing (lo>1) and leading (hi<count)', () => {
        expect(isPartialTake([10, 12], 12)).toBe(true); // trailing
        expect(isPartialTake([1, 7], 8)).toBe(true); // leading
        expect(isPartialTake([1, 8], 8)).toBe(false); // full
        expect(isPartialTake([1, 4], 0)).toBe(false); // unknown count → trailing-only
    });

    it('isWaslBridge requires the flag AND a different next verse', () => {
        const a = seg('14:1', 0, 1, 13, 16, true);
        expect(isWaslBridge(a, seg('14:2', 1, 2, 1, 9))).toBe(true);
        expect(isWaslBridge(a, seg('14:1', 1, 2, 1, 9))).toBe(false); // same verse
        expect(isWaslBridge(seg('14:1', 0, 1, 1, 16), seg('14:2', 1, 2, 1, 9))).toBe(false); // no flag
        expect(isWaslBridge(a, null)).toBe(false);
    });
});
