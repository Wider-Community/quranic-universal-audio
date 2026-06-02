/**
 * `friendlyError(body, status)` is the single translation layer that keeps
 * raw backend prose (which leaks internal state tokens / capability IDs) out
 * of toasts. These tests pin the three guarantees: code wins, status is the
 * fallback, and `body.error` is NEVER surfaced.
 */

import { describe, expect, it } from 'vitest';

import { friendlyError } from '../friendly';

describe('friendlyError', () => {
    it('maps a known code to friendly copy', () => {
        expect(friendlyError({ code: 'MARKED_READY_FROZEN' }, 403)).toContain(
            'marked ready for publish',
        );
        expect(friendlyError({ code: 'NOT_CLAIM_HOLDER' }, 403)).toContain('active claim');
    });

    it('interpolates context.state_label for NOT_EDITABLE_STATE', () => {
        const msg = friendlyError(
            { code: 'NOT_EDITABLE_STATE', context: { state_label: 'published' } },
            403,
        );
        expect(msg).toContain('published');
    });

    it('falls back gracefully when state_label is absent', () => {
        const msg = friendlyError({ code: 'STATE_PRECONDITION' }, 400);
        expect(msg.length).toBeGreaterThan(0);
        expect(msg).not.toContain('undefined');
    });

    it('falls back to a status message for an unknown code', () => {
        expect(friendlyError({ code: 'SOMETHING_NEW' }, 403)).toBe(
            "You don't have permission for this action.",
        );
        expect(friendlyError({}, 404)).toBe("That couldn't be found.");
    });

    it('returns a generic message for an unmapped status', () => {
        expect(friendlyError(undefined, 418)).toBe('Something went wrong. Please try again.');
    });

    it('NEVER surfaces the raw backend error string', () => {
        const leaky = 'released requires UNDER_REVIEW, got AWAITING_TIMESTAMPS';
        const msg = friendlyError({ error: leaky, code: 'STATE_PRECONDITION' }, 400);
        expect(msg).not.toContain(leaky);
        expect(msg).not.toContain('UNDER_REVIEW');
        // Even with no code, the raw prose must not appear.
        expect(friendlyError({ error: leaky }, 400)).not.toContain(leaky);
    });
});
