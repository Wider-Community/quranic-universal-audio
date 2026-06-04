// Derived selectors return correct slices over SegmentState.

import { get } from 'svelte/store';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { segAllData, selectedChapter } from '../../stores/chapter';
import { derivedTimings } from '../../stores/filters';
import {
  findByUid,
  getAdjacentSegments,
  getChapterSegments,
  getSegByChapterIndex,
  segmentsStore,
} from '../../stores/segments';
import { makeSegment } from '../helpers/make-segment';

// Reset the shared chapter store between test groups so a previous run's
// segAllData / selectedChapter can't leak into the next describe block.
function setupStore(): () => void {
  return () => {
    segAllData.set(null);
    selectedChapter.set('');
  };
}

const sampleState = () => ({
  byId: {
    'uid-1': makeSegment(0, 0, 1000, { segment_uid: 'uid-1' }),
    'uid-2': makeSegment(1, 1000, 2000, { segment_uid: 'uid-2' }),
    'uid-3': makeSegment(2, 2000, 3000, { segment_uid: 'uid-3' }),
  },
  idsByChapter: { 1: ['uid-1', 'uid-2'], 2: ['uid-3'] },
  selectedChapter: 1 as number | null,
});

describe('normalized-state selectors', () => {
  it('getChapterSegments returns ids resolved against byId', () => {
    const segs = getChapterSegments(sampleState() as any, 1);
    expect(segs.map((s: any) => s.segment_uid)).toEqual(['uid-1', 'uid-2']);
  });

  it('getSegByChapterIndex resolves correctly', () => {
    const seg = getSegByChapterIndex(sampleState() as any, 1, 1);
    expect((seg as any).segment_uid).toBe('uid-2');
  });

  it('getAdjacentSegments returns prev/next pair', () => {
    const adj = getAdjacentSegments(sampleState() as any, 1, 1);
    expect(adj.prev?.segment_uid).toBe('uid-1');
    expect(adj.next).toBeFalsy();
  });

  it('findByUid returns segment when present', () => {
    const seg = findByUid(sampleState() as any, 'uid-2');
    expect((seg as any).segment_uid).toBe('uid-2');
  });

  it('selectors return new array references on state change (subscribe-friendly)', () => {
    const s1 = sampleState();
    const a = getChapterSegments(s1 as any, 1);
    const s2 = { ...s1, byId: { ...s1.byId } };
    const b = getChapterSegments(s2 as any, 1);
    expect(a).not.toBe(b);
  });
});

describe('segmentsStore load-path wiring (IS-7)', () => {
  let teardown: () => void = () => {};

  beforeAll(() => {
    teardown = setupStore();
  });

  afterAll(() => {
    teardown();
  });

  it('segmentsStore populates from segAllData when load-path fires', () => {
    const segs = [
      { ...makeSegment(0, 0, 1000, { segment_uid: 'load-uid-1' }), chapter: 7 },
      { ...makeSegment(1, 1000, 2000, { segment_uid: 'load-uid-2' }), chapter: 7 },
    ];
    segAllData.set({ segments: segs, audio_by_chapter: {}, pad_ms: 0, pad_left_ms: 0, pad_right_ms: 0, min_silence_floor_ms: 0 } as any);
    selectedChapter.set('7');
    const state: any = get(segmentsStore);
    expect(Object.keys(state.byId).sort()).toEqual(['load-uid-1', 'load-uid-2']);
    expect(state.idsByChapter[7]).toEqual(['load-uid-1', 'load-uid-2']);
    expect(state.selectedChapter).toBe(7);
    segAllData.set(null);
    selectedChapter.set('');
  });

  it('segmentsStore returns empty state when segAllData is cleared', () => {
    segAllData.set(null);
    selectedChapter.set('');
    const state: any = get(segmentsStore);
    expect(state.byId).toEqual({});
    expect(state.idsByChapter).toEqual({});
    expect(state.selectedChapter).toBeNull();
  });
});

describe('derivedTimings (silence_after derivation)', () => {
  let teardown: () => void = () => {};

  beforeAll(() => {
    teardown = setupStore();
  });

  afterAll(() => {
    teardown();
  });

  it('derives silence_after_ms from segment adjacency within an entry', () => {
    const audio = 'https://example/a.mp3';
    const segs = [
      { ...makeSegment(0, 0, 1000, { segment_uid: 't-uid-1' }), chapter: 1, audio_url: audio, entry_idx: 0 },
      { ...makeSegment(1, 1500, 2500, { segment_uid: 't-uid-2' }), chapter: 1, audio_url: audio, entry_idx: 0 },
      { ...makeSegment(2, 3000, 4000, { segment_uid: 't-uid-3' }), chapter: 1, audio_url: audio, entry_idx: 0 },
    ];
    segAllData.set({ segments: segs, audio_by_chapter: {}, pad_ms: 100, pad_left_ms: 100, pad_right_ms: 100, min_silence_floor_ms: 0 } as any);
    const map: any = get(derivedTimings);
    expect(map.get('t-uid-1')).toEqual({
      silence_after_ms: (1500 - 1000) + 200,
      silence_after_raw_ms: 1500 - 1000,
    });
    expect(map.get('t-uid-2')).toEqual({
      silence_after_ms: (3000 - 2500) + 200,
      silence_after_raw_ms: 3000 - 2500,
    });
    // Last segment in the entry has no "next" -> null timing.
    expect(map.get('t-uid-3')).toEqual({
      silence_after_ms: null,
      silence_after_raw_ms: null,
    });
    segAllData.set(null);
  });

  it('returns null timings across entry boundaries (different audio_url)', () => {
    const segs = [
      { ...makeSegment(0, 0, 1000, { segment_uid: 'x-uid-1' }), chapter: 1, audio_url: 'a', entry_idx: 0 },
      { ...makeSegment(1, 1500, 2500, { segment_uid: 'x-uid-2' }), chapter: 1, audio_url: 'b', entry_idx: 0 },
    ];
    segAllData.set({ segments: segs, audio_by_chapter: {}, pad_ms: 0, pad_left_ms: 0, pad_right_ms: 0, min_silence_floor_ms: 0 } as any);
    const map: any = get(derivedTimings);
    expect(map.get('x-uid-1')?.silence_after_ms).toBeNull();
    segAllData.set(null);
  });
});
