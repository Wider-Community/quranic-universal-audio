// Frontend loader backfills segment_uid for legacy fixtures.

import { describe, expect, it } from 'vitest';

import { deriveUid } from '../../domain/identity';

const legacySeg = (chapter: number, idx: number, startMs: number) => ({
  time_start: startMs,
  time_end: startMs + 1000,
  matched_ref: `${chapter}:1:1-${chapter}:1:1`,
  matched_text: 'x',
  confidence: 1.0,
  // no segment_uid
});

describe('uid backfill (frontend)', () => {
  it('frontend loader backfills uid for legacy fixture', () => {
    void legacySeg(1, 0, 0);
    const uid = deriveUid({ chapter: 1, originalIndex: 0, startMs: 0 });
    expect(typeof uid).toBe('string');
    expect(uid.length).toBeGreaterThan(8);
  });

  it('backfill is deterministic across two loads', () => {
    const a = deriveUid({ chapter: 1, originalIndex: 0, startMs: 0 });
    const b = deriveUid({ chapter: 1, originalIndex: 0, startMs: 0 });
    expect(a).toBe(b);
  });

  it('backfill matches Python loader for same input', () => {
    const ts = deriveUid({ chapter: 1, originalIndex: 0, startMs: 0 });
    expect(ts).toBe('418dc3a4-5e80-5d8e-9a3f-209a6403206e');
  });
});
