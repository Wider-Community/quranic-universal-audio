// Auto-suppress decoupling — edits MUST NOT mutate ignored_categories.
//
// `ignored_categories` reflects only explicit Ignore actions. Editing from
// a validation accordion card records the source category on the op
// (op_context_category, for history pills) but never writes to the
// segment's persisted ignore list. Card dismissal for soft-rule
// categories is handled out-of-band via the session-resolved store.

import { describe, expect,it } from 'vitest';

import { CAN_IGNORE_CATEGORIES } from '../helpers/categories';
import { makeSegment } from '../helpers/make-segment';
import { loadOptional } from '../helpers/optional';

const mod = await loadOptional<{ applyCommand: any }>('../../domain/apply-command');
const applyCommand = mod?.applyCommand ?? null;

const baseState = () => ({
  byId: { 'uid-as': makeSegment(0, 0, 1000, { segment_uid: 'uid-as' }) },
  idsByChapter: { 1: ['uid-as'] },
  selectedChapter: 1 as number | null,
});

describe.skipIf(!applyCommand)('command/auto-suppress (decoupled)', () => {
  for (const cat of CAN_IGNORE_CATEGORIES) {
    it(`edit dispatched with sourceCategory='${cat}' does NOT add ${cat} to seg.ignored_categories`, () => {
      const r = applyCommand(baseState(), {
        type: 'editReference',
        segmentUid: 'uid-as',
        matched_ref: '1:1:1-1:1:1',
        matched_text: 'x',
        sourceCategory: cat,
      } as any);
      const updated = r.nextState.byId?.['uid-as'] ?? r.nextState['uid-as'];
      expect(updated.ignored_categories ?? []).not.toContain(cat);
    });
  }

  it('op records sourceCategory in op_context_category for history audit', () => {
    const r = applyCommand(baseState(), {
      type: 'editReference',
      segmentUid: 'uid-as',
      matched_ref: '1:1:1-1:1:1',
      matched_text: 'x',
      sourceCategory: 'boundary_adj',
    } as any);
    expect(r.operation.op_context_category).toBe('boundary_adj');
  });

  it('trim with sourceCategory does not mutate ignored_categories', () => {
    const r = applyCommand(baseState(), {
      type: 'trim',
      segmentUid: 'uid-as',
      delta: { time_start: 100, time_end: 900 },
      sourceCategory: 'audio_bleeding',
    } as any);
    const updated = r.nextState.byId?.['uid-as'] ?? r.nextState['uid-as'];
    expect(updated.ignored_categories ?? []).not.toContain('audio_bleeding');
  });

  it('main-list edit (no sourceCategory) does not mutate ignored_categories', () => {
    const r = applyCommand(baseState(), {
      type: 'trim',
      segmentUid: 'uid-as',
      delta: { time_start: 100, time_end: 900 },
    } as any);
    const updated = r.nextState.byId?.['uid-as'] ?? r.nextState['uid-as'];
    expect(updated.ignored_categories ?? []).toEqual([]);
  });

  it('preserves pre-existing ignored_categories on the segment', () => {
    const state = {
      byId: {
        'uid-as': makeSegment(0, 0, 1000, {
          segment_uid: 'uid-as',
          ignored_categories: ['low_confidence'],
        }),
      },
      idsByChapter: { 1: ['uid-as'] },
      selectedChapter: 1 as number | null,
    };
    const r = applyCommand(state, {
      type: 'trim',
      segmentUid: 'uid-as',
      delta: { time_start: 100, time_end: 900 },
      sourceCategory: 'boundary_adj',
    } as any);
    const updated = r.nextState.byId?.['uid-as'] ?? r.nextState['uid-as'];
    expect(updated.ignored_categories).toEqual(['low_confidence']);
  });
});

describe.skipIf(applyCommand)('command/auto-suppress (deferred)', () => {
  it.todo('phase-3: domain/apply-command not yet present');
});
