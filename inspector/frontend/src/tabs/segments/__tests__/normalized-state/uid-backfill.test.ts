// Frontend loader backfills segment_uid for legacy fixtures.

import { describe, expect, it } from 'vitest';

import { backfillSegmentUids, deriveUid } from '../../domain/identity';

const legacySeg = (
  chapter: number,
  idx: number,
  startMs: number,
): { segment_uid?: string; time_start: number; time_end: number; matched_ref: string; matched_text: string; confidence: number } => ({
  time_start: startMs,
  time_end: startMs + 1000,
  matched_ref: `${chapter}:1:1-${chapter}:1:1`,
  matched_text: 'x',
  confidence: 1.0,
  // no segment_uid
});

describe('uid backfill (frontend)', () => {
  it('backfillSegmentUids mutates legacy fixture in place with deterministic uids', () => {
    const segs = [legacySeg(1, 0, 0)];
    backfillSegmentUids(segs as Array<{ segment_uid?: string; time_start: number }>, 1);
    const seg = segs[0]!;
    expect(typeof seg.segment_uid).toBe('string');
    expect(seg.segment_uid!.length).toBeGreaterThan(8);
    // Backfilled uid must match a direct deriveUid call with the same inputs.
    expect(seg.segment_uid).toBe(
      deriveUid({ chapter: 1, originalIndex: 0, startMs: 0 }),
    );
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
