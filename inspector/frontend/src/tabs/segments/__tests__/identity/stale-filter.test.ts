// Phase 6: filterStaleIssues helper.

import { describe, it, expect } from 'vitest';
import { loadOptional } from '../helpers/optional';

const stale = await loadOptional<any>('../../utils/validation/stale');

describe.skipIf(!stale)('filterStaleIssues', () => {
  it('drops items whose uid is not in current state', () => {
    const issues = [{ segment_uid: 'old' }, { segment_uid: 'alive' }];
    const live = new Set(['alive']);
    const out = stale.filterStaleIssues(issues, live);
    expect(out).toHaveLength(1);
  });

  it('keeps items whose uid is in current state', () => {
    const issues = [{ segment_uid: 'alive' }];
    const live = new Set(['alive']);
    const out = stale.filterStaleIssues(issues, live);
    expect(out).toHaveLength(1);
  });

  it('keeps legacy issues (no uid) for seg_index resolution', () => {
    const issues = [{ seg_index: 0 }];
    const live = new Set(['alive']);
    const out = stale.filterStaleIssues(issues, live);
    expect(out).toHaveLength(1);
  });
});

describe.skipIf(stale)('filterStaleIssues (deferred)', () => {
  it.todo('phase-6: utils/validation/stale not yet present');
});
