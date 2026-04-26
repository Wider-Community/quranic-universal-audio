// auto-suppress parametrized over the registry's per-segment categories.

import { describe, it, expect } from 'vitest';
import { makeSegment } from '../helpers/make-segment';
import { CAN_IGNORE_CATEGORIES, AUTO_SUPPRESS_CATEGORIES } from '../helpers/categories';
import { loadOptional } from '../helpers/optional';

const mod = await loadOptional<{ applyCommand: any }>('../../domain/apply-command');
const applyCommand = mod?.applyCommand ?? null;

const baseState = () => ({
  byId: { 'uid-as': makeSegment(0, 0, 1000, { segment_uid: 'uid-as' }) },
  idsByChapter: { 1: ['uid-as'] },
  selectedChapter: 1 as number | null,
});

describe.skipIf(!applyCommand)('command/auto-suppress', () => {
  for (const cat of CAN_IGNORE_CATEGORIES) {
    it(`for category ${cat} with auto_suppress=Y, an edit dispatched with sourceCategory adds C to seg.ignored_categories`, () => {
      const r = applyCommand(baseState(), {
        type: 'editReference',
        segmentUid: 'uid-as',
        matched_ref: '1:1:1-1:1:1',
        matched_text: 'x',
        sourceCategory: cat,
      } as any);
      const updated = r.nextState.byId?.['uid-as'] ?? r.nextState['uid-as'];
      if (AUTO_SUPPRESS_CATEGORIES.includes(cat as any)) {
        expect(updated.ignored_categories).toContain(cat);
      } else {
        expect(updated.ignored_categories ?? []).not.toContain(cat);
      }
    });
  }

  it('for category C with auto_suppress=N, an edit dispatched with sourceCategory does not add C', () => {
    const r = applyCommand(baseState(), {
      type: 'editReference',
      segmentUid: 'uid-as',
      matched_ref: '1:1:1-1:1:1',
      matched_text: 'x',
      sourceCategory: 'muqattaat',
    } as any);
    const updated = r.nextState.byId?.['uid-as'] ?? r.nextState['uid-as'];
    expect((updated.ignored_categories ?? [])).not.toContain('muqattaat');
  });

  it('muqattaat is never auto-suppressed regardless of edit context', () => {
    const r = applyCommand(baseState(), { type: 'editReference', segmentUid: 'uid-as', matched_ref: '2:1:1-2:1:1', matched_text: 'x', sourceCategory: 'muqattaat' } as any);
    const updated = r.nextState.byId?.['uid-as'] ?? r.nextState['uid-as'];
    expect((updated.ignored_categories ?? [])).not.toContain('muqattaat');
  });
});

describe.skipIf(applyCommand)('command/auto-suppress (deferred)', () => {
  it.todo('phase-3: domain/apply-command not yet present');
});
