// Session-resolved store + filterSessionResolved helper.
//
// Edits dispatched from a soft-resolve category card mark
// `(segment_uid, category)` as resolved-this-session so the
// ValidationPanel hides those cards even when the post-save validator
// still flags them. Pure in-memory; cleared on chapter switch / reciter
// change / page reload.

import { describe, it, expect, beforeEach } from 'vitest';
import {
  markSessionResolved,
  isSessionResolved,
  clearSessionResolved,
  getSessionResolvedSnapshot,
} from '../../stores/session-resolved';
import { filterSessionResolved } from '../../utils/validation/stale';

describe('session-resolved store', () => {
  beforeEach(() => {
    clearSessionResolved();
  });

  it('markSessionResolved adds (uid, category) to the set', () => {
    markSessionResolved('uid-1', 'boundary_adj');
    expect(isSessionResolved('uid-1', 'boundary_adj')).toBe(true);
  });

  it('isSessionResolved returns false for unmarked pairs', () => {
    markSessionResolved('uid-1', 'boundary_adj');
    expect(isSessionResolved('uid-1', 'qalqala')).toBe(false);
    expect(isSessionResolved('uid-2', 'boundary_adj')).toBe(false);
  });

  it('marking is idempotent', () => {
    markSessionResolved('uid-1', 'boundary_adj');
    markSessionResolved('uid-1', 'boundary_adj');
    const snap = getSessionResolvedSnapshot();
    expect(snap.get('uid-1')!.size).toBe(1);
  });

  it('multiple categories on same uid coexist', () => {
    markSessionResolved('uid-1', 'boundary_adj');
    markSessionResolved('uid-1', 'audio_bleeding');
    expect(isSessionResolved('uid-1', 'boundary_adj')).toBe(true);
    expect(isSessionResolved('uid-1', 'audio_bleeding')).toBe(true);
  });

  it('clearSessionResolved empties the store', () => {
    markSessionResolved('uid-1', 'boundary_adj');
    markSessionResolved('uid-2', 'qalqala');
    clearSessionResolved();
    expect(isSessionResolved('uid-1', 'boundary_adj')).toBe(false);
    expect(isSessionResolved('uid-2', 'qalqala')).toBe(false);
    expect(getSessionResolvedSnapshot().size).toBe(0);
  });

  it('null/empty uid is a no-op for marking and reading', () => {
    markSessionResolved('', 'boundary_adj');
    markSessionResolved(null, 'boundary_adj');
    markSessionResolved(undefined, 'boundary_adj');
    expect(getSessionResolvedSnapshot().size).toBe(0);
    expect(isSessionResolved(null, 'boundary_adj')).toBe(false);
  });
});

describe('filterSessionResolved', () => {
  it('drops items whose (uid, category) pair is in the resolved map', () => {
    const issues = [
      { segment_uid: 'uid-1', kind: 'boundary_adj' } as any,
      { segment_uid: 'uid-2', kind: 'boundary_adj' } as any,
    ];
    const map = new Map([['uid-1', new Set(['boundary_adj'])]]);
    const out = filterSessionResolved(issues, 'boundary_adj', map);
    expect(out).toHaveLength(1);
    expect((out[0] as any).segment_uid).toBe('uid-2');
  });

  it('keeps items when the category does not match', () => {
    const issues = [{ segment_uid: 'uid-1', kind: 'qalqala' } as any];
    const map = new Map([['uid-1', new Set(['boundary_adj'])]]);
    const out = filterSessionResolved(issues, 'qalqala', map);
    expect(out).toHaveLength(1);
  });

  it('passes through items with no segment_uid (chapter/verse-level cards)', () => {
    const issues = [{ kind: 'structural_errors' } as any, { segment_uid: null, kind: 'structural_errors' } as any];
    const map = new Map([['uid-1', new Set(['boundary_adj'])]]);
    const out = filterSessionResolved(issues, 'structural_errors', map);
    expect(out).toHaveLength(2);
  });

  it('returns input unchanged when the resolved map is empty', () => {
    const issues = [{ segment_uid: 'uid-1', kind: 'boundary_adj' } as any];
    const out = filterSessionResolved(issues, 'boundary_adj', new Map());
    expect(out).toBe(issues);
  });
});
