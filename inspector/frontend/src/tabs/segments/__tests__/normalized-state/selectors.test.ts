// Phase 4: derived selectors return correct slices over SegmentState.

import { describe, it, expect } from 'vitest';
import { get } from 'svelte/store';
import { makeSegment } from '../helpers/make-segment';
import { loadOptional } from '../helpers/optional';

const segmentsStore = await loadOptional<any>('../../stores/segments');
const chapterStore = await loadOptional<any>('../../stores/chapter');
const filtersStore = await loadOptional<any>('../../stores/filters');
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
  it('getChapterSegments returns ids resolved against byId', () => {
    const segs = (selectors.getChapterSegments ?? selectors.default)(sampleState(), 1);
    expect(segs.map((s: any) => s.segment_uid)).toEqual(['uid-1', 'uid-2']);
  });

  it('getSegByChapterIndex resolves correctly', () => {
    const seg = selectors.getSegByChapterIndex(sampleState(), 1, 1);
    expect(seg.segment_uid).toBe('uid-2');
  });

  it('getAdjacentSegments returns prev/next pair', () => {
    const adj = selectors.getAdjacentSegments(sampleState(), 1, 1);
    expect(adj.prev?.segment_uid).toBe('uid-1');
    expect(adj.next).toBeFalsy();
  });

  it('findByUid returns segment when present', () => {
    const seg = selectors.findByUid(sampleState(), 'uid-2');
    expect(seg.segment_uid).toBe('uid-2');
  });

  it('selectors return new array references on state change (subscribe-friendly)', () => {
    const s1 = sampleState();
    const a = selectors.getChapterSegments(s1, 1);
    const s2 = { ...s1, byId: { ...s1.byId } };
    const b = selectors.getChapterSegments(s2, 1);
    expect(a).not.toBe(b);
  });
});

describe.skipIf(!segmentsStore || !chapterStore)('segmentsStore load-path wiring (IS-7)', () => {
  it('segmentsStore populates from segAllData when load-path fires', () => {
    const store = segmentsStore.segmentsStore;
    const segs = [
      { ...makeSegment(0, 0, 1000, { segment_uid: 'load-uid-1' }), chapter: 7 },
      { ...makeSegment(1, 1000, 2000, { segment_uid: 'load-uid-2' }), chapter: 7 },
    ];
    chapterStore.segAllData.set({ segments: segs, audio_by_chapter: {}, pad_ms: 0 });
    chapterStore.selectedChapter.set('7');
    const state: any = get(store);
    expect(Object.keys(state.byId).sort()).toEqual(['load-uid-1', 'load-uid-2']);
    expect(state.idsByChapter[7]).toEqual(['load-uid-1', 'load-uid-2']);
    expect(state.selectedChapter).toBe(7);
    chapterStore.segAllData.set(null);
    chapterStore.selectedChapter.set('');
  });

  it('segmentsStore returns empty state when segAllData is cleared', () => {
    const store = segmentsStore.segmentsStore;
    chapterStore.segAllData.set(null);
    chapterStore.selectedChapter.set('');
    const state: any = get(store);
    expect(state.byId).toEqual({});
    expect(state.idsByChapter).toEqual({});
    expect(state.selectedChapter).toBeNull();
  });
});

describe.skipIf(!filtersStore || !chapterStore)('derivedTimings (silence_after derivation)', () => {
  it('derives silence_after_ms from segment adjacency within an entry', () => {
    const audio = 'https://example/a.mp3';
    const segs = [
      { ...makeSegment(0, 0, 1000, { segment_uid: 't-uid-1' }), chapter: 1, audio_url: audio, entry_idx: 0 },
      { ...makeSegment(1, 1500, 2500, { segment_uid: 't-uid-2' }), chapter: 1, audio_url: audio, entry_idx: 0 },
      { ...makeSegment(2, 3000, 4000, { segment_uid: 't-uid-3' }), chapter: 1, audio_url: audio, entry_idx: 0 },
    ];
    chapterStore.segAllData.set({ segments: segs, audio_by_chapter: {}, pad_ms: 100 });
    const map: any = get(filtersStore.derivedTimings);
    expect(map.get('t-uid-1')).toEqual({
      silence_after_ms: (1500 - 1000) + 2 * 100,
      silence_after_raw_ms: 1500 - 1000,
    });
    expect(map.get('t-uid-2')).toEqual({
      silence_after_ms: (3000 - 2500) + 2 * 100,
      silence_after_raw_ms: 3000 - 2500,
    });
    // Last segment in the entry has no "next" -> null timing.
    expect(map.get('t-uid-3')).toEqual({
      silence_after_ms: null,
      silence_after_raw_ms: null,
    });
    chapterStore.segAllData.set(null);
  });

  it('returns null timings across entry boundaries (different audio_url)', () => {
    const segs = [
      { ...makeSegment(0, 0, 1000, { segment_uid: 'x-uid-1' }), chapter: 1, audio_url: 'a', entry_idx: 0 },
      { ...makeSegment(1, 1500, 2500, { segment_uid: 'x-uid-2' }), chapter: 1, audio_url: 'b', entry_idx: 0 },
    ];
    chapterStore.segAllData.set({ segments: segs, audio_by_chapter: {}, pad_ms: 0 });
    const map: any = get(filtersStore.derivedTimings);
    expect(map.get('x-uid-1')?.silence_after_ms).toBeNull();
    chapterStore.segAllData.set(null);
  });
});
