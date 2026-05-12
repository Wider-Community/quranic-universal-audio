/**
 * `syncEditingMode(currentUser, task)` is the load-bearing helper that
 * maps `(user, reciter-task)` to an `EditingMode`. Every branch matters
 * because the resulting popover copy is user-visible and the editGate
 * action gates real save/undo affordances.
 */

import { describe, expect, it } from 'vitest';

import type { ReciterTask, ReciterTaskState, Visibility } from '../../api/reciter-task';
import type { CurrentUser, Role } from '../current-user';
import { syncEditingMode } from '../editing-mode';

function _user(overrides: Partial<CurrentUser> = {}): CurrentUser {
    return {
        login: 'alice',
        hf_user_id: 'u-1',
        role: 'contributor' as Role,
        active_claim: null,
        ...overrides,
    };
}

function _task(overrides: {
    state?: ReciterTaskState;
    marked_ready?: boolean;
    visibility?: Visibility;
    assignee_hf_id?: string | null;
} = {}): ReciterTask {
    return {
        row: {
            slug: 'test_slug',
            name: 'Test Reciter',
            state: overrides.state ?? 'awaiting_review',
            state_since: '2026-05-12T00:00:00Z',
            assignee_hf_id: overrides.assignee_hf_id ?? null,
            assignee_login: overrides.assignee_hf_id ? 'bob' : null,
            assignee_since: overrides.assignee_hf_id ? '2026-05-12T00:00:00Z' : null,
            marked_ready: overrides.marked_ready ?? false,
            visibility: overrides.visibility ?? 'public',
        },
        predicates: {
            can_claim: false,
            can_edit: false,
            can_edit_as_admin: false,
            can_mark_ready: false,
            can_unmark_ready: false,
            can_release: false,
        },
    };
}

describe('syncEditingMode', () => {
    it('returns view/unauthenticated when user is null', () => {
        expect(syncEditingMode(null, _task())).toEqual({
            kind: 'view',
            viewReason: 'unauthenticated',
        });
    });

    it('returns view/unauthenticated when task is null', () => {
        expect(syncEditingMode(_user(), null)).toEqual({
            kind: 'view',
            viewReason: 'unauthenticated',
        });
    });

    it('returns view/discarded when visibility is discarded', () => {
        const task = _task({ state: 'under_review', visibility: 'discarded', assignee_hf_id: 'u-1' });
        expect(syncEditingMode(_user(), task)).toEqual({
            kind: 'view',
            viewReason: 'discarded',
        });
    });

    it('returns view/completed for completed reciter', () => {
        const task = _task({ state: 'completed' });
        expect(syncEditingMode(_user(), task)).toEqual({
            kind: 'view',
            viewReason: 'completed',
        });
    });

    it('returns view/released for post-publish reciter', () => {
        const task = _task({ state: 'released' });
        expect(syncEditingMode(_user(), task)).toEqual({
            kind: 'view',
            viewReason: 'released',
        });
    });

    it('returns view/marked_ready when assignee marked their own claim', () => {
        const task = _task({
            state: 'under_review',
            marked_ready: true,
            assignee_hf_id: 'u-1',
        });
        expect(syncEditingMode(_user(), task)).toEqual({
            kind: 'view',
            viewReason: 'marked_ready',
        });
    });

    it('returns editor for the active reviewer on an under_review row', () => {
        const task = _task({ state: 'under_review', assignee_hf_id: 'u-1' });
        expect(syncEditingMode(_user(), task)).toEqual({ kind: 'editor' });
    });

    it('returns maintainer for a maintainer viewing someone else\'s active claim', () => {
        const task = _task({ state: 'under_review', assignee_hf_id: 'other' });
        expect(syncEditingMode(_user({ role: 'maintainer' }), task)).toEqual({
            kind: 'maintainer',
        });
    });

    it('returns owner for an owner viewing someone else\'s active claim', () => {
        const task = _task({ state: 'under_review', assignee_hf_id: 'other' });
        expect(syncEditingMode(_user({ role: 'owner' }), task)).toEqual({
            kind: 'owner',
        });
    });

    it('returns view/wrong-assignee for a contributor on someone else\'s under_review', () => {
        const task = _task({ state: 'under_review', assignee_hf_id: 'other' });
        expect(syncEditingMode(_user(), task)).toEqual({
            kind: 'view',
            viewReason: 'wrong-assignee',
        });
    });

    it('admin sees marked_ready as wrong-assignee (frozen for non-assignee admin)', () => {
        const task = _task({
            state: 'under_review',
            marked_ready: true,
            assignee_hf_id: 'other',
        });
        // Admin override doesn't apply when row is marked_ready — that's the
        // contract: marked_ready is frozen until the reviewer unmarks or a
        // maintainer publishes via the dedicated admin endpoint (Phase 5).
        expect(syncEditingMode(_user({ role: 'maintainer' }), task)).toEqual({
            kind: 'view',
            viewReason: 'wrong-assignee',
        });
    });

    it('returns view/not-claimable for catalogued / awaiting_alignment rows', () => {
        for (const state of ['catalogued', 'awaiting_alignment', 'awaiting_timestamps'] as const) {
            const task = _task({ state });
            expect(syncEditingMode(_user(), task)).toEqual({
                kind: 'view',
                viewReason: 'not-claimable',
            });
        }
    });

    it('returns view/unauthenticated for hf_user_id=null signed-in shape', () => {
        // Anonymous shape — currentUser has all fields null when /api/me
        // returned anonymous. Treat as not-signed-in.
        const anon: CurrentUser = {
            login: null,
            hf_user_id: null,
            role: null,
            active_claim: null,
        };
        expect(syncEditingMode(anon, _task())).toEqual({
            kind: 'view',
            viewReason: 'unauthenticated',
        });
    });
});
