// filterStaleIssues helper.

import { describe, expect, it } from 'vitest';

import { filterStaleIssues } from '../../utils/validation/stale';

describe('filterStaleIssues', () => {
  it('drops items whose uid is not in current state', () => {
    const issues = [{ segment_uid: 'old' }, { segment_uid: 'alive' }];
    const live = new Set(['alive']);
    const out = filterStaleIssues(issues as any, live);
    expect(out).toHaveLength(1);
  });

  it('keeps items whose uid is in current state', () => {
    const issues = [{ segment_uid: 'alive' }];
    const live = new Set(['alive']);
    const out = filterStaleIssues(issues as any, live);
    expect(out).toHaveLength(1);
  });

  it('keeps legacy issues (no uid) for seg_index resolution', () => {
    const issues = [{ seg_index: 0 }];
    const live = new Set(['alive']);
    const out = filterStaleIssues(issues as any, live);
    expect(out).toHaveLength(1);
  });
});
