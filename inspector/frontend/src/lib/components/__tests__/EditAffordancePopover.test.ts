import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';

import { editPopover, showEditPopover } from '../../stores/edit-popover';
import EditAffordancePopover from '../EditAffordancePopover.svelte';

afterEach(() => {
    editPopover.set(null);
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

        await tick();
        await tick();

        const popover = container.querySelector<HTMLElement>('.edit-popover');
        expect(popover).not.toBeNull();
        expect(popover?.textContent).toContain('Reciter under review');
        expect(popover?.style.top).toBe('98px');
        expect(popover?.style.left).toBe('120px');
    });
});
