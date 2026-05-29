import { render } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import type { ReciterTask } from '../../api/reciter-task';
import { currentUser } from '../../stores/current-user';
import ClaimButton from '../ClaimButton.svelte';

function makeTask(canClaim: boolean): ReciterTask {
    return {
        row: {
            slug: 'other-reciter',
            name: 'Other',
            state: 'awaiting_review',
            state_since: '2026-01-01T00:00:00Z',
            assignee_hf_id: null,
            assignee_login: null,
            assignee_since: null,
            marked_ready: false,
            visibility: 'public',
        },
        predicates: {
            can_claim: canClaim,
            can_edit: false,
            can_edit_as_admin: false,
            can_edit_as_owner: false,
            can_mark_ready: false,
            can_unmark_ready: false,
            can_release: false,
        },
    } as ReciterTask;
}

describe('ClaimButton', () => {
    it('renders nothing when a contributor holds another active claim, even if can_claim is true', () => {
        currentUser.set({
            login: 'me',
            hf_user_id: 'u-1',
            role: 'contributor',
            active_claim: 'some-other-slug',
            active_claims: ['some-other-slug'],
            dev_mode: false,
            capabilities: [],
        });

        const { container } = render(ClaimButton, {
            props: {
                slug: 'this-reciter',
                task: makeTask(true),
                onClaimed: null,
            },
        });

        expect(container.querySelector('button')).toBeNull();
        expect(container.textContent ?? '').not.toMatch(/Already claiming/);
    });

    it('renders the Claim button for an owner with an existing active claim (multi-claim exempt)', () => {
        currentUser.set({
            login: 'me',
            hf_user_id: 'u-1',
            role: 'owner',
            active_claim: 'some-other-slug',
            active_claims: ['some-other-slug'],
            dev_mode: false,
            capabilities: [],
        });

        const { container } = render(ClaimButton, {
            props: {
                slug: 'second-target',
                task: makeTask(true),
                onClaimed: null,
            },
        });

        expect(container.querySelector('button')).not.toBeNull();
    });

    it('renders the Claim button when can_claim is true and no foreign active claim', () => {
        currentUser.set({
            login: 'me',
            hf_user_id: 'u-1',
            role: 'contributor',
            active_claim: null,
            active_claims: [],
            dev_mode: false,
            capabilities: [],
        });

        const { container } = render(ClaimButton, {
            props: {
                slug: 'target',
                task: makeTask(true),
                onClaimed: null,
            },
        });

        const btn = container.querySelector('button');
        expect(btn).not.toBeNull();
        expect(btn!.classList.contains('seg-btn')).toBe(true);
        expect(btn!.classList.contains('primary')).toBe(true);
        expect(btn!.classList.contains('lg')).toBe(false);
    });
});
