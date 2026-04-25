// applyCommand reducer tests (IS-5).

import { describe, it, expect } from 'vitest';
import { xfail } from '../helpers/xfail';
import { makeSegment } from '../helpers/make-segment';
import { loadOptional } from '../helpers/optional';

const mod = await loadOptional<{ applyCommand: any }>('../../domain/apply-command');
const applyCommand = mod?.applyCommand ?? null;

describe.skipIf(!applyCommand)('applyCommand', () => {
  const baseState = {
    byId: { 'uid-1': makeSegment(0, 0, 1000, { segment_uid: 'uid-1' }) },
    idsByChapter: { 1: ['uid-1'] },
    selectedChapter: 1 as number | null,
  };

  it('returns CommandResult with nextState', () => {
    const r = applyCommand(baseState, { type: 'trim', segmentUid: 'uid-1', delta: { time_start: 100 } } as any);
    expect(r.nextState).toBeTruthy();
  });

  it('returns operation matching createOp shape', () => {
    const r = applyCommand(baseState, { type: 'trim', segmentUid: 'uid-1', delta: { time_start: 100 } } as any);
    expect(r.operation).toBeTruthy();
    expect(r.operation.type).toBe('trim');
  });

  it('returns affectedChapters list', () => {
    const r = applyCommand(baseState, { type: 'trim', segmentUid: 'uid-1', delta: { time_start: 100 } } as any);
    expect(Array.isArray(r.affectedChapters)).toBe(true);
    expect(r.affectedChapters).toContain(1);
  });

  it('returns validationDelta when applicable', () => {
    const r = applyCommand(baseState, { type: 'editReference', segmentUid: 'uid-1', matched_ref: '1:1:1-1:1:1' } as any);
    expect('validationDelta' in r).toBe(true);
  });

  it('returns patch field (stub in Phase 3, populated in Phase 5)', xfail('phase-5', () => {
    const r = applyCommand(baseState, { type: 'trim', segmentUid: 'uid-1', delta: { time_start: 100 } } as any);
    expect(r.patch).toBeTruthy();
    expect(Array.isArray(r.patch.before)).toBe(true);
    expect(Array.isArray(r.patch.after)).toBe(true);
  }));
});

describe.skipIf(applyCommand)('applyCommand (deferred)', () => {
  it.todo('phase-3: domain/apply-command not yet present');
});
