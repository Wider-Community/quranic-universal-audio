// Compat selectors preserve $segData / $segAllData read shape.

import { describe, expect, it } from 'vitest';

import * as chapterStore from '../../stores/chapter';
import * as segmentsStore from '../../stores/segments';

void segmentsStore;

describe('compat shape', () => {
  it('segData exposes a subscribe function', () => {
    expect(typeof chapterStore.segData?.subscribe).toBe('function');
  });

  it('segAllData snapshot does not expose internal _byChapter / _byChapterIndex maps', () => {
    let snapshot: any;
    chapterStore.segAllData.subscribe((v: any) => { snapshot = v; })();
    expect(snapshot).toBeDefined();
    expect(snapshot?._byChapter).toBeUndefined();
    expect(snapshot?._byChapterIndex).toBeUndefined();
  });

  it('segData and segAllData expose subscribe functions', () => {
    expect(typeof chapterStore.segData.subscribe).toBe('function');
    expect(typeof chapterStore.segAllData.subscribe).toBe('function');
  });
});
