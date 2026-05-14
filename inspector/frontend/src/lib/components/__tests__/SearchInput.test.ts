import { fireEvent, render } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import SearchInput from '../SearchInput.svelte';

describe('SearchInput', () => {
    it('renders the count label when count and total are set', () => {
        const { container } = render(SearchInput, {
            props: { value: '', placeholder: 'Search reciters', count: 3, total: 10 },
        });
        expect(container.querySelector('.count')?.textContent).toBe('3 of 10');
    });

    it('omits the count label when count is null', () => {
        const { container } = render(SearchInput, {
            props: { value: '', placeholder: 'Search', count: null, total: 10 },
        });
        expect(container.querySelector('.count')).toBeNull();
    });

    it('omits the count label when total is null', () => {
        const { container } = render(SearchInput, {
            props: { value: '', placeholder: 'Search', count: 3, total: null },
        });
        expect(container.querySelector('.count')).toBeNull();
    });

    it('dispatches the input event with the new value', async () => {
        const { container, component } = render(SearchInput, {
            props: { value: '', placeholder: 'Search' },
        });

        const fired: string[] = [];
        component.$on('input', (e: CustomEvent<string>) => fired.push(e.detail));

        const input = container.querySelector('input')!;
        await fireEvent.input(input, { target: { value: 'abu bakr' } });

        expect(fired).toEqual(['abu bakr']);
    });
});
