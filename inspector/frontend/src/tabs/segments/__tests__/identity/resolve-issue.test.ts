// Issue resolution: uid-first with seg_index fallback for legacy items.
//
// The resolver reads `segment_uid` from the issue first and only falls
// back to `seg_index` for issues that lack a uid. It consults `byId`
// before any chapter+index lookup. Stale uids (absent from current state)
// return null even when seg_index would resolve.

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { segAllData } from '../../stores/chapter';
import { resolveByUidStrict, resolveIssueSeg } from '../../utils/validation/resolve-issue';

// Set up a minimal in-memory segment store so uid-first lookups resolve.
// Chapter 1 has one segment: { segment_uid: 'fixture-uid', index: 0 }.
function setupStore(): () => void {
  const seg = {
    segment_uid: 'fixture-uid',
    index: 0,
    chapter: 1,
    time_start: 0,
    time_end: 1000,
    matched_ref: '1:1:1-1:1:1',
    matched_text: '',
    confidence: 1.0,
    audio_url: '',
  };
  segAllData.set({
    segments: [seg],
    audio_by_chapter: {},
    pad_ms: 0,
    pad_left_ms: 0,
    pad_right_ms: 0,
    min_silence_floor_ms: 0,
  } as any);
  return () => segAllData.set(null);
}

describe('resolveIssueSeg', () => {
  let teardown: (() => void) | null = null;

  beforeAll(() => {
    teardown = setupStore();
  });

  afterAll(() => {
    teardown?.();
  });

  it('uses segment_uid first when both uid and seg_index would resolve to different segments', () => {
    // Override the store with two segments so we can distinguish uid-first
    // from seg_index-first. Seeding only one segment that matches by both
    // ids can't distinguish the two strategies.
    const segA = {
      segment_uid: 'fixture-uid',
      index: 7,
      chapter: 1,
      time_start: 0, time_end: 1000,
      matched_ref: '1:1:1-1:1:1', matched_text: '', confidence: 1.0, audio_url: '',
    };
    const segB = {
      segment_uid: 'other-uid',
      index: 0,
      chapter: 1,
      time_start: 2000, time_end: 3000,
      matched_ref: '1:1:1-1:1:1', matched_text: '', confidence: 1.0, audio_url: '',
    };
    segAllData.set({
      segments: [segA, segB],
      audio_by_chapter: {}, pad_ms: 0, pad_left_ms: 0, pad_right_ms: 0,
      min_silence_floor_ms: 0,
    } as any);
    try {
      const item = { segment_uid: 'fixture-uid', seg_index: 0, chapter: 1 };
      const seg = resolveIssueSeg(item as any, 'low_confidence', null);
      expect(seg).toBeTruthy();
      // uid wins: returns segA (index 7), not segB (index 0).
      expect((seg as any).segment_uid).toBe('fixture-uid');
      expect((seg as any).index).toBe(7);
    } finally {
      // Restore the single-segment store the rest of this describe relies on.
      teardown?.();
      teardown = setupStore();
    }
  });

  it('falls back to seg_index for legacy issues', () => {
    const item = { seg_index: 0, chapter: 1 };
    const seg = resolveIssueSeg(item as any, 'low_confidence', null);
    expect(seg).toBeTruthy();
  });

  it('returns null for stale uid', () => {
    const item = { segment_uid: 'no-such-uid', seg_index: 0, chapter: 1 };
    const seg = resolveIssueSeg(item as any, 'low_confidence', null);
    expect(typeof resolveByUidStrict).toBe('function');
    expect(seg).toBeFalsy();
  });

  it('exposes resolveIssueSeg as a function', () => {
    expect(typeof resolveIssueSeg).toBe('function');
  });
});
