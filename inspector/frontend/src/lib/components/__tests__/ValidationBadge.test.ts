import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';

import ValidationBadge from '../ValidationBadge.svelte';

describe('ValidationBadge', () => {
    it('renders the label and count', () => {
        const { container } = render(ValidationBadge, { label: 'Errors', count: 3 });
        const badge = container.querySelector('.val-badge');
        expect(badge).not.toBeNull();
        expect(badge?.textContent?.trim()).toBe('Errors: 3');
    });

    it('applies the has-errors class when count > 0', () => {
        const { container } = render(ValidationBadge, { label: 'Warnings', count: 5 });
        const badge = container.querySelector('.val-badge');
        expect(badge?.classList.contains('has-errors')).toBe(true);
    });

    it('omits the has-errors class when count is zero', () => {
        const { container } = render(ValidationBadge, { label: 'Passed', count: 0 });
        const badge = container.querySelector('.val-badge');
        expect(badge?.classList.contains('has-errors')).toBe(false);
    });

    it('applies tone-error when tone prop is "error" and count > 0', () => {
        const { container } = render(ValidationBadge, {
            label: 'Failed',
            count: 2,
            tone: 'error',
        });
        const badge = container.querySelector('.val-badge');
        expect(badge?.classList.contains('tone-error')).toBe(true);
    });

    it('applies tone-warning when tone prop is "warning" and count > 0', () => {
        const { container } = render(ValidationBadge, {
            label: 'Low confidence',
            count: 7,
            tone: 'warning',
        });
        const badge = container.querySelector('.val-badge');
        expect(badge?.classList.contains('tone-warning')).toBe(true);
    });
});
