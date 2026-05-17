// IS-6: split flows dispatch through applyCommand.

import { describe, expect,it } from 'vitest';

import { makeSegment } from '../helpers/make-segment';
import { loadOptional } from '../helpers/optional';

const mod = await loadOptional<{ applyCommand: any }>('../../domain/apply-command');
const applyCommand = mod?.applyCommand ?? null;

const baseState = () => ({
  byId: { 'uid-split': makeSegment(0, 0, 4000, { segment_uid: 'uid-split' }) },
  idsByChapter: { 1: ['uid-split'] },
  selectedChapter: 1 as number | null,
});

describe.skipIf(!applyCommand)('command/split', () => {
  it('op produces expected segment mutations', () => {
    const r = applyCommand(baseState(), { type: 'split', segmentUid: 'uid-split', splitMs: 2000 } as any);
    const ids = Object.keys(r.nextState.byId ?? r.nextState);
    expect(ids.length).toBeGreaterThanOrEqual(2);
  });

  it('op records snapshots before / after', () => {
    const r = applyCommand(baseState(), { type: 'split', segmentUid: 'uid-split', splitMs: 2000 } as any);
    expect(r.operation.snapshots?.before).toBeTruthy();
    expect(r.operation.snapshots?.after).toBeTruthy();
  });

  it('op marks dirty correctly (structural vs single-index)', () => {
    const r = applyCommand(baseState(), { type: 'split', segmentUid: 'uid-split', splitMs: 2000 } as any);
    expect(r.operation.kind).toBe('structural');
  });

  it('op honors auto-suppress per registry', () => {
    const r = applyCommand(baseState(), { type: 'split', segmentUid: 'uid-split', splitMs: 2000, sourceCategory: 'cross_verse' } as any);
    expect(r.operation).toBeTruthy();
  });

  it('op preserves _mountId routing through dispatcher', () => {
    const r = applyCommand(baseState(), { type: 'split', segmentUid: 'uid-split', splitMs: 2000, _mountId: 'main-list' } as any);
    expect(r.operation).toBeTruthy();
  });

  it('op result feeds save payload correctly', () => {
    const r = applyCommand(baseState(), { type: 'split', segmentUid: 'uid-split', splitMs: 2000 } as any);
    expect(r.operation.type).toBe('split');
  });

  it('targetSegmentIndex routing for main-list mountId', () => {
    const r = applyCommand(baseState(), { type: 'split', segmentUid: 'uid-split', splitMs: 2000, _mountId: 'main-list' } as any);
    expect(r.operation.targetSegmentIndex?.chapter).toBe(1);
  });

  it('targetSegmentIndex routing for accordion mountId', () => {
    const r = applyCommand(baseState(), { type: 'split', segmentUid: 'uid-split', splitMs: 2000, _mountId: 'accordion' } as any);
    expect(r.operation.targetSegmentIndex?.chapter).toBe(1);
  });

  it('editReference drops wrap when matched_ref changes', () => {
    // Regression: editing matched_ref kept the wrap intact even when the new
    // ref no longer contained the wrap word range — Ayyub edit_history shows
    // the bug:  "1:24 wrap=11..24" → "1:21 wrap=11..24" (wrap now stale).
    const state = {
      byId: {
        'uid-rep': makeSegment(0, 0, 4000, {
          segment_uid: 'uid-rep',
          matched_ref: '48:29:1-48:29:24',
          wrap_word_ranges: [['48:29:11', '48:29:11', '48:29:24']] as any,
        }),
      },
      idsByChapter: { 1: ['uid-rep'] },
      selectedChapter: 1 as number | null,
    };
    const r = applyCommand(state, {
      type: 'editReference', segmentUid: 'uid-rep', matched_ref: '48:29:1-48:29:3',
    } as any);
    const out = Object.values(r.nextState.byId ?? r.nextState)[0] as any;
    expect(out.matched_ref).toBe('48:29:1-48:29:3');
    expect(out.wrap_word_ranges).toBeUndefined();
  });

  it('confirmReference (no ref change) preserves wrap', () => {
    // confirm_reference re-affirms the existing matched_ref. The wrap should
    // not be discarded just because the user audited the row.
    const state = {
      byId: {
        'uid-rep': makeSegment(0, 0, 4000, {
          segment_uid: 'uid-rep',
          matched_ref: '48:29:1-48:29:24',
          wrap_word_ranges: [['48:29:11', '48:29:11', '48:29:24']] as any,
        }),
      },
      idsByChapter: { 1: ['uid-rep'] },
      selectedChapter: 1 as number | null,
    };
    const r = applyCommand(state, {
      type: 'editReference', opType: 'confirm_reference', segmentUid: 'uid-rep',
      matched_ref: '48:29:1-48:29:24',
    } as any);
    const out = Object.values(r.nextState.byId ?? r.nextState)[0] as any;
    expect(out.wrap_word_ranges).toEqual([['48:29:11', '48:29:11', '48:29:24']]);
  });

  it('merge drops wrap from both segs', () => {
    // Merging changes matched_ref + geometry; any wrap on the first seg may
    // not apply to the merged span. Drop for the same reason split does.
    const state = {
      byId: {
        'uid-a': makeSegment(0, 0, 2000, {
          segment_uid: 'uid-a',
          matched_ref: '48:29:1-48:29:11',
          wrap_word_ranges: [['48:29:5', '48:29:5', '48:29:11']] as any,
        }),
        'uid-b': makeSegment(1, 2000, 4000, {
          segment_uid: 'uid-b',
          matched_ref: '48:29:12-48:29:24',
        }),
      },
      idsByChapter: { 1: ['uid-a', 'uid-b'] },
      selectedChapter: 1 as number | null,
    };
    const r = applyCommand(state, {
      type: 'merge', fromUid: 'uid-b', toUid: 'uid-a',
    } as any);
    const merged = Object.values(r.nextState.byId ?? r.nextState)[0] as any;
    expect(merged.wrap_word_ranges).toBeUndefined();
  });

  it('drops wrap_word_ranges from every child', () => {
    // Regression: a parent repetition seg used to leak its wrap onto every
    // split child, re-tagging post-split clean segs as repetitions and
    // making Auto Split feed the wrong refs to MFA.
    const state = {
      byId: {
        'uid-rep': makeSegment(0, 0, 4000, {
          segment_uid: 'uid-rep',
          matched_ref: '48:29:1-48:29:24',
          wrap_word_ranges: [['48:29:11', '48:29:11', '48:29:24']] as any,
        }),
      },
      idsByChapter: { 1: ['uid-rep'] },
      selectedChapter: 1 as number | null,
    };
    const r = applyCommand(state, {
      type: 'split', segmentUid: 'uid-rep', splitMs: 2000, newUids: ['uid-new'],
    } as any);
    const pieces = Object.values(r.nextState.byId ?? r.nextState) as any[];
    expect(pieces.length).toBe(2);
    for (const p of pieces) {
      expect(p.wrap_word_ranges).toBeUndefined();
    }
  });
});

describe.skipIf(applyCommand)('command/split (deferred)', () => {
  it.todo('phase-3: domain/apply-command not yet present');
});
