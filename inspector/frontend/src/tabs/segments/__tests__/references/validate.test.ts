/**
 * _validateRefStructural — gate used by commitRefEdit to decide between
 * dispatch (ok), silent fix (word_overshoot + clamped), and red-badge
 * re-entry (malformed / unknown_verse).
 */

import { describe, it, expect } from 'vitest';
import { _validateRefStructural } from '../../utils/data/references';

const vwc = { '1:1': 4, '1:2': 5 };

describe('_validateRefStructural', () => {
    it('canonical valid ref → ok', () => {
        expect(_validateRefStructural('1:1:1-1:1:3', vwc))
            .toEqual({ ok: true, ref: '1:1:1-1:1:3' });
    });

    it('malformed (no dash) → malformed', () => {
        expect(_validateRefStructural('1:1:1', vwc))
            .toEqual({ ok: false, reason: 'malformed' });
    });

    it('malformed (non-numeric) → malformed', () => {
        expect(_validateRefStructural('a:b:c-1:1:2' as any, vwc))
            .toEqual({ ok: false, reason: 'malformed' });
    });

    it('end before start within same verse → malformed', () => {
        expect(_validateRefStructural('1:1:3-1:1:2', vwc))
            .toEqual({ ok: false, reason: 'malformed' });
    });

    it('unknown verse → unknown_verse', () => {
        expect(_validateRefStructural('1:99:1-1:99:2', vwc))
            .toEqual({ ok: false, reason: 'unknown_verse' });
    });

    it('word overshoot within known verse → word_overshoot with clamped', () => {
        const r = _validateRefStructural('1:1:1-1:1:9', vwc);
        expect(r).toEqual({ ok: false, reason: 'word_overshoot', clamped: '1:1:1-1:1:4' });
    });

    it('empty ref → malformed', () => {
        expect(_validateRefStructural('', vwc))
            .toEqual({ ok: false, reason: 'malformed' });
    });

    it('without vwc: structural-only check (cannot detect overshoot)', () => {
        // 1:1:1-1:1:9 looks structurally valid without vwc to compare against.
        expect(_validateRefStructural('1:1:1-1:1:9', undefined))
            .toEqual({ ok: true, ref: '1:1:1-1:1:9' });
    });
});
