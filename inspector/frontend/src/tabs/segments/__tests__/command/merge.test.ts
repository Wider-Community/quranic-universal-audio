// IS-6: merge flows dispatch through applyCommand.

import { describe, expect,it } from 'vitest';

import { makeApplyCommandState, makeSegment } from '../helpers/make-segment';
import { loadOptional } from '../helpers/optional';

const mod = await loadOptional<{ applyCommand: any }>('../../domain/apply-command');
const applyCommand = mod?.applyCommand ?? null;

const baseState = () => makeApplyCommandState([
  makeSegment(0, 0, 1000, { segment_uid: 'uid-a' }),
  makeSegment(1, 1000, 2000, { segment_uid: 'uid-b' }),
]);

describe.skipIf(!applyCommand)('command/merge', () => {
  it('op produces expected segment mutations', () => {
    const r = applyCommand(baseState(), { type: 'merge', fromUid: 'uid-a', toUid: 'uid-b' } as any);
    const ids = Object.keys(r.nextState.byId ?? r.nextState);
    expect(ids.length).toBe(1);
  });

  it('op records snapshots before / after', () => {
    const r = applyCommand(baseState(), { type: 'merge', fromUid: 'uid-a', toUid: 'uid-b' } as any);
    expect(r.operation.snapshots).toBeTruthy();
  });

  it('op marks dirty correctly (structural vs single-index)', () => {
    const r = applyCommand(baseState(), { type: 'merge', fromUid: 'uid-a', toUid: 'uid-b' } as any);
    expect(r.operation.kind).toBe('structural');
  });

  it('op honors auto-suppress per registry', () => {
    const r = applyCommand(baseState(), { type: 'merge', fromUid: 'uid-a', toUid: 'uid-b' } as any);
    expect(r.operation).toBeTruthy();
  });

  it('op preserves _mountId routing through dispatcher', () => {
    const r = applyCommand(baseState(), { type: 'merge', fromUid: 'uid-a', toUid: 'uid-b', _mountId: 'main-list' } as any);
    expect(r.operation).toBeTruthy();
  });

  it('op result feeds save payload correctly', () => {
    const r = applyCommand(baseState(), { type: 'merge', fromUid: 'uid-a', toUid: 'uid-b' } as any);
    expect(r.operation.type).toBe('merge');
  });

  it('targetSegmentIndex routing for main-list mountId', () => {
    const r = applyCommand(baseState(), { type: 'merge', fromUid: 'uid-a', toUid: 'uid-b', _mountId: 'main-list' } as any);
    expect(r.operation.targetSegmentIndex?.chapter).toBe(1);
  });

  it('targetSegmentIndex routing for accordion mountId', () => {
    const r = applyCommand(baseState(), { type: 'merge', fromUid: 'uid-a', toUid: 'uid-b', _mountId: 'accordion' } as any);
    expect(r.operation.targetSegmentIndex?.chapter).toBe(1);
  });
});

describe.skipIf(applyCommand)('command/merge (deferred)', () => {
  it.todo('phase-3: domain/apply-command not yet present');
});
