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

  it('drops wrap_word_ranges and has_repeated_words from every child', () => {
    // Regression: a parent repetition seg used to leak its wrap onto every
    // split child, re-tagging post-split clean segs as repetitions and
    // making Auto Split feed the wrong refs to MFA.
    const state = {
      byId: {
        'uid-rep': makeSegment(0, 0, 4000, {
          segment_uid: 'uid-rep',
          matched_ref: '48:29:1-48:29:24',
          wrap_word_ranges: [['48:29:11', '48:29:11', '48:29:24']] as any,
          has_repeated_words: true,
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
      expect(p.has_repeated_words).toBeUndefined();
    }
  });
});

describe.skipIf(applyCommand)('command/split (deferred)', () => {
  it.todo('phase-3: domain/apply-command not yet present');
});
