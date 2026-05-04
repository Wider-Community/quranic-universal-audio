// Phase 4: compat selectors preserve $segData / $segAllData read shape.

import { describe, it, expect } from 'vitest';
import { loadOptional } from '../helpers/optional';

const chapterStore = await loadOptional<any>('../../stores/chapter');
const segmentsStore = await loadOptional<any>('../../stores/segments');

describe.skipIf(!chapterStore)('compat shape', () => {
  it('$segData has same shape as before refactor', () => {
    if (!segmentsStore) throw new Error('phase-4: stores/segments not yet present');
    expect(typeof chapterStore.segData?.subscribe).toBe('function');
  });

  it('$segAllData has same shape (no _byChapter / _byChapterIndex exposed)', () => {
    if (!segmentsStore) throw new Error('phase-4: stores/segments not yet present');
    let snapshot: any;
    chapterStore.segAllData.subscribe((v: any) => { snapshot = v; })();
    expect(snapshot).toBeDefined();
    expect(snapshot?._byChapter).toBeUndefined();
    expect(snapshot?._byChapterIndex).toBeUndefined();
  });

  it('existing components subscribe without modification', () => {
    if (!segmentsStore) throw new Error('phase-4: stores/segments not yet present');
    expect(typeof chapterStore.segData.subscribe).toBe('function');
    expect(typeof chapterStore.segAllData.subscribe).toBe('function');
  });
});

describe.skipIf(chapterStore)('compat shape (deferred)', () => {
  it.todo('phase-4: stores/chapter.ts not yet refactored to derive from segments.ts');
});
