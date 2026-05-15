import { fireEvent, render, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it, vi } from 'vitest';

import TimeEdit from '../TimeEdit.svelte';

describe('TimeEdit Enter commit', () => {
    it('commits a valid time without leaving inline edit mode', async () => {
        const onCommit = vi.fn();
        const onTimeClick = vi.fn();
        const initialProps = {
            value: 6000,
            bounds: { min: 0, max: 20000 },
            editing: true,
            autoFocusGroup: 'ss' as const,
            onTimeClick,
            onCommit,
        };
        const { container, rerender } = render(TimeEdit, initialProps);

        await waitFor(() => {
            expect(container.querySelector('.seg-time-group-input')).not.toBeNull();
        });

        const input = container.querySelector<HTMLInputElement>('.seg-time-group-input');
        expect(input).not.toBeNull();

        await fireEvent.input(input!, { target: { value: '7' } });
        await fireEvent.keyDown(input!, { key: 'Enter' });

        expect(onCommit).toHaveBeenCalledTimes(1);
        expect(onCommit).toHaveBeenCalledWith(7000);

        const committedInput = container.querySelector<HTMLInputElement>('.seg-time-group-input');
        expect(committedInput).not.toBeNull();
        expect(committedInput?.value).toBe('07');

        await rerender({ ...initialProps, value: 7000 });
        await tick();

        const syncedInput = container.querySelector<HTMLInputElement>('.seg-time-group-input');
        expect(syncedInput).not.toBeNull();
        expect(syncedInput?.value).toBe('07');
    });
});
