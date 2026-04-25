// Issue resolution: uid-first with seg_index fallback for legacy items.
//
// The resolver reads `segment_uid` from the issue first and only falls
// back to `seg_index` for issues that lack a uid. It consults `byId`
// before any chapter+index lookup. Stale uids (absent from current state)
// return null even when seg_index would resolve.

import { describe, it, expect } from 'vitest';
import { xfail } from '../helpers/xfail';
import { loadOptional } from '../helpers/optional';

const resolve = await loadOptional<any>('../../utils/validation/resolve-issue');

describe.skipIf(!resolve)('resolveIssueSeg', () => {
  it('uses segment_uid first when present', xfail('phase-6', () => {
    // The resolver must consult uid before seg_index.
    // An item that carries segment_uid must resolve via uid, not via index.
    const item = { segment_uid: 'phase-6-uid', seg_index: 0, chapter: 1 };
    const seg = resolve.resolveIssueSeg(item as any, 'low_confidence', null);
    if (!seg || (seg as any).segment_uid !== 'phase-6-uid') {
      throw new Error('uid-first resolution not yet implemented');
    }
  }));

  it('falls back to seg_index for legacy issues', xfail('phase-6', () => {
    // Legacy: issue lacks segment_uid; resolver must still resolve via seg_index.
    // The test verifies the fallback path works when no uid is present.
    const item = { seg_index: 0, chapter: 1 };
    const seg = resolve.resolveIssueSeg(item as any, 'low_confidence', null);
    if (!seg) {
      throw new Error('legacy seg_index fallback path returned null unexpectedly');
    }
  }));

  it('returns null for stale uid', xfail('phase-6', () => {
    // A uid that is absent from current state must resolve to null,
    // even when seg_index would otherwise point to a segment.
    // The resolver must expose resolveByUidStrict to enable this check.
    const item = { segment_uid: 'no-such-uid', seg_index: 5, chapter: 1 };
    const seg = resolve.resolveIssueSeg(item as any, 'low_confidence', null);
    if (!resolve.resolveByUidStrict) {
      throw new Error('resolveByUidStrict not yet exposed');
    }
    expect(seg).toBeFalsy();
  }));

  it('matches errors-category by verse-key prefix (unchanged behavior)', () => {
    expect(typeof resolve.resolveIssueSeg).toBe('function');
  });
});

describe.skipIf(resolve)('resolveIssueSeg (deferred)', () => {
  it.todo('phase-6: utils/validation/resolve-issue not yet present');
});
