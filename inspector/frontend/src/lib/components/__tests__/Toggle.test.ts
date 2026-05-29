import { fireEvent, render } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import Toggle from '../Toggle.svelte';

describe('Toggle', () => {
    it('renders a switch reflecting checked state', () => {
        const { getByRole } = render(Toggle, { props: { checked: true } });
        const sw = getByRole('switch');
        expect(sw.getAttribute('aria-checked')).toBe('true');
    });

    it('fires onchange with the toggled value on click', async () => {
        const onchange = vi.fn();
        const { getByRole } = render(Toggle, { props: { checked: false, onchange } });
        await fireEvent.click(getByRole('switch'));
        expect(onchange).toHaveBeenCalledWith(true);
    });

    it('toggles on Enter and Space', async () => {
        const onchange = vi.fn();
        const { getByRole } = render(Toggle, { props: { checked: true, onchange } });
        const sw = getByRole('switch');
        await fireEvent.keyDown(sw, { key: 'Enter' });
        await fireEvent.keyDown(sw, { key: ' ' });
        expect(onchange).toHaveBeenCalledTimes(2);
        expect(onchange).toHaveBeenCalledWith(false);
    });

    it('suppresses onchange when disabled', async () => {
        const onchange = vi.fn();
        const { getByRole } = render(Toggle, {
            props: { checked: false, disabled: true, onchange },
        });
        await fireEvent.click(getByRole('switch'));
        expect(onchange).not.toHaveBeenCalled();
    });

    it('suppresses onchange when busy', async () => {
        const onchange = vi.fn();
        const { getByRole } = render(Toggle, {
            props: { checked: false, busy: true, onchange },
        });
        await fireEvent.click(getByRole('switch'));
        expect(onchange).not.toHaveBeenCalled();
    });

    it('renders a non-switch N/A marker when na', () => {
        const { queryByRole, getByText } = render(Toggle, {
            props: { checked: false, na: true },
        });
        expect(queryByRole('switch')).toBeNull();
        expect(getByText('N/A')).toBeTruthy();
    });
});
