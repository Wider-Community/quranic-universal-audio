// Phase 4: derived selectors return correct slices over SegmentState.

import { describe, it, expect } from 'vitest';
import { xfail } from '../helpers/xfail';
import { makeSegment } from '../helpers/make-segment';
import { loadOptional } from '../helpers/optional';

const segmentsStore = await loadOptional<any>('../../stores/segments');
const selectors = segmentsStore;

const sampleState = () => ({
  byId: {
    'uid-1': makeSegment(0, 0, 1000, { segment_uid: 'uid-1' }),
    'uid-2': makeSegment(1, 1000, 2000, { segment_uid: 'uid-2' }),
    'uid-3': makeSegment(2, 2000, 3000, { segment_uid: 'uid-3' }),
  },
  idsByChapter: { 1: ['uid-1', 'uid-2'], 2: ['uid-3'] },
  selectedChapter: 1 as number | null,
});

describe.skipIf(!segmentsStore)('normalized-state selectors', () => {
  it('getChapterSegments returns ids resolved against byId', xfail('phase-4', () => {
    const segs = (selectors.getChapterSegments ?? selectors.default)(sampleState(), 1);
    expect(segs.map((s: any) => s.segment_uid)).toEqual(['uid-1', 'uid-2']);
  }));

  it('getSegByChapterIndex resolves correctly', xfail('phase-4', () => {
    const seg = selectors.getSegByChapterIndex(sampleState(), 1, 1);
    expect(seg.segment_uid).toBe('uid-2');
  }));

  it('getAdjacentSegments returns prev/next pair', xfail('phase-4', () => {
    const adj = selectors.getAdjacentSegments(sampleState(), 1, 1);
    expect(adj.prev?.segment_uid).toBe('uid-1');
    expect(adj.next).toBeFalsy();
  }));

  it('findByUid returns segment when present', xfail('phase-4', () => {
    const seg = selectors.findByUid(sampleState(), 'uid-2');
    expect(seg.segment_uid).toBe('uid-2');
  }));

  it('selectors return new array references on state change (subscribe-friendly)', xfail('phase-4', () => {
    const s1 = sampleState();
    const a = selectors.getChapterSegments(s1, 1);
    const s2 = { ...s1, byId: { ...s1.byId } };
    const b = selectors.getChapterSegments(s2, 1);
    expect(a).not.toBe(b);
  }));
});

describe.skipIf(segmentsStore)('normalized-state selectors (deferred)', () => {
  it.todo('phase-4: stores/segments.ts not yet present');
});
