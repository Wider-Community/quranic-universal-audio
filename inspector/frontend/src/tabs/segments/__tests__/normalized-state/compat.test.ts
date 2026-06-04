// Compat selectors preserve $segData / $segAllData read shape.

import { describe, expect, it } from 'vitest';

import * as chapterStore from '../../stores/chapter';
import * as segmentsStore from '../../stores/segments';

void segmentsStore;

describe('compat shape', () => {
  it('segAllData snapshot carries the documented SegAllResponse fields and no private byChapter map', () => {
    const sample = {
      segments: [],
      audio_by_chapter: {},
      pad_ms: 0,
      pad_left_ms: 0,
      pad_right_ms: 0,
      min_silence_floor_ms: 0,
    };
    chapterStore.segAllData.set(sample as any);
    let snapshot: any;
    const unsub = chapterStore.segAllData.subscribe((v: any) => { snapshot = v; });
    unsub();
    expect(snapshot).not.toBeNull();
    // Documented fields survive — proves consumers can keep reading them.
    expect(Array.isArray(snapshot.segments)).toBe(true);
    expect(snapshot.audio_by_chapter).toBeDefined();
    expect(snapshot.pad_ms).toBe(0);
    expect(snapshot.pad_left_ms).toBe(0);
    expect(snapshot.pad_right_ms).toBe(0);
    expect(snapshot.min_silence_floor_ms).toBe(0);
    // Internal byChapter maps must not leak through the store (would
    // otherwise tempt consumers into depending on private structure).
    expect(snapshot._byChapter).toBeUndefined();
    expect(snapshot._byChapterIndex).toBeUndefined();
  });
});
