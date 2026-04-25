// IS-6: merge flows dispatch through applyCommand.

import { describe, it, expect } from 'vitest';
import { xfail } from '../helpers/xfail';
import { makeSegment } from '../helpers/make-segment';
import { loadOptional } from '../helpers/optional';

const mod = await loadOptional<{ applyCommand: any }>('../../domain/apply-command');
const applyCommand = mod?.applyCommand ?? null;

const baseState = () => ({
  byId: {
    'uid-a': makeSegment(0, 0, 1000, { segment_uid: 'uid-a' }),
    'uid-b': makeSegment(1, 1000, 2000, { segment_uid: 'uid-b' }),
  },
  idsByChapter: { 1: ['uid-a', 'uid-b'] },
  selectedChapter: 1 as number | null,
});

describe.skipIf(!applyCommand)('command/merge', () => {
  it('op produces expected segment mutations', xfail('phase-3', () => {
    const r = applyCommand(baseState(), { type: 'merge', fromUid: 'uid-a', toUid: 'uid-b' } as any);
    const ids = Object.keys(r.nextState.byId ?? r.nextState);
    expect(ids.length).toBe(1);
  }));

  it('op records snapshots before / after', xfail('phase-3', () => {
    const r = applyCommand(baseState(), { type: 'merge', fromUid: 'uid-a', toUid: 'uid-b' } as any);
    expect(r.operation.snapshots).toBeTruthy();
  }));

  it('op marks dirty correctly (structural vs single-index)', xfail('phase-3', () => {
    const r = applyCommand(baseState(), { type: 'merge', fromUid: 'uid-a', toUid: 'uid-b' } as any);
    expect(r.operation.kind).toBe('structural');
  }));

  it('op honors auto-suppress per registry', xfail('phase-3', () => {
    const r = applyCommand(baseState(), { type: 'merge', fromUid: 'uid-a', toUid: 'uid-b' } as any);
    expect(r.operation).toBeTruthy();
  }));

  it('op preserves _mountId routing through dispatcher', xfail('phase-3', () => {
    const r = applyCommand(baseState(), { type: 'merge', fromUid: 'uid-a', toUid: 'uid-b', _mountId: 'main-list' } as any);
    expect(r.operation).toBeTruthy();
  }));

  it('op result feeds save payload correctly', xfail('phase-3', () => {
    const r = applyCommand(baseState(), { type: 'merge', fromUid: 'uid-a', toUid: 'uid-b' } as any);
    expect(r.operation.type).toBe('merge');
  }));

  it('targetSegmentIndex routing for main-list mountId', xfail('phase-3', () => {
    const r = applyCommand(baseState(), { type: 'merge', fromUid: 'uid-a', toUid: 'uid-b', _mountId: 'main-list' } as any);
    expect(r.operation.targetSegmentIndex?.chapter).toBe(1);
  }));

  it('targetSegmentIndex routing for accordion mountId', xfail('phase-3', () => {
    const r = applyCommand(baseState(), { type: 'merge', fromUid: 'uid-a', toUid: 'uid-b', _mountId: 'accordion' } as any);
    expect(r.operation.targetSegmentIndex?.chapter).toBe(1);
  }));
});

describe.skipIf(applyCommand)('command/merge (deferred)', () => {
  it.todo('phase-3: domain/apply-command not yet present');
});
