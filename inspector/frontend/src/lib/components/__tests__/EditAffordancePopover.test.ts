import { render, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { afterEach, describe, expect, it } from 'vitest';

import { selectedReciter } from '../../../tabs/segments/stores/chapter';
import { claimConfirmModal, closeClaimConfirm } from '../../stores/claim-confirm-modal';
import { editPopover, showEditPopover } from '../../stores/edit-popover';
import EditAffordancePopover from '../EditAffordancePopover.svelte';

afterEach(() => {
    editPopover.set(null);
    closeClaimConfirm();
    claimConfirmModal.set({ open: false, slug: null, onClaimed: null });
    selectedReciter.set('');
    document.body.innerHTML = '';
});

describe('EditAffordancePopover', () => {
    it('positions next to the anchor on the first blocked edit click', async () => {
        const anchor = document.createElement('button');
        document.body.appendChild(anchor);
        anchor.getBoundingClientRect = () => ({
            top: 70,
            right: 180,
            bottom: 90,
            left: 120,
            width: 60,
            height: 20,
            x: 120,
            y: 70,
            toJSON: () => ({}),
        });

        const { container } = render(EditAffordancePopover);
        showEditPopover(anchor, { kind: 'view', viewReason: 'wrong-assignee' });

        const popover = await waitFor(() => {
            const el = container.querySelector<HTMLElement>('.edit-popover');
            expect(el).not.toBeNull();
            expect(el?.style.top).toBe('98px');
            return el!;
        });
        expect(popover.textContent).toContain('Being edited by someone else');
        expect(popover.style.left).toBe('120px');
    });

    it('renders a "Claim review" action for the claimable reason that opens the confirm modal', async () => {
        const anchor = document.createElement('button');
        document.body.appendChild(anchor);
        anchor.getBoundingClientRect = () => ({
            top: 70, right: 180, bottom: 90, left: 120, width: 60, height: 20,
            x: 120, y: 70, toJSON: () => ({}),
        });
        selectedReciter.set('reciter-claimable');

        const { getByText } = render(EditAffordancePopover);
        showEditPopover(anchor, { kind: 'view', viewReason: 'claimable' });

        const cta = await waitFor(() => getByText('Claim review'));
        cta.click();

        const state = get(claimConfirmModal);
        expect(state.open).toBe(true);
        expect(state.slug).toBe('reciter-claimable');
        // Popover dismisses when the action fires.
        expect(get(editPopover)).toBeNull();
    });
});
