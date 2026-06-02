import { fireEvent, render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import Modal from '../Modal.svelte';

describe('Modal — close paths + body scroll lock', () => {
    beforeEach(() => {
        // happy-dom defaults document.body.style.overflow to '' (empty);
        // re-assert just in case.
        document.body.style.overflow = '';
    });
    afterEach(() => {
        document.body.style.overflow = '';
    });

    it('renders nothing when closed', () => {
        const { container } = render(Modal, { props: { open: false, title: 'X' } });
        expect(container.querySelector('.modal')).toBeNull();
    });

    it('renders the title and a close button when open', () => {
        const { container } = render(Modal, { props: { open: true, title: 'Pick reciter' } });
        const title = container.querySelector('.modal-title');
        expect(title?.textContent).toBe('Pick reciter');
        expect(container.querySelector('.modal-close')).not.toBeNull();
    });

    it('renders a close button even when no title is provided', () => {
        const { container } = render(Modal, { props: { open: true, title: null } });
        expect(container.querySelector('.modal-close')).not.toBeNull();
    });

    it('dispatches close on the close button click', async () => {
        const onClose = vi.fn();
        const { container } = render(Modal, {
            props: { open: true, title: 'X' },
            events: { close: onClose },
        });
        await fireEvent.click(container.querySelector('.modal-close')!);
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('dispatches close on Escape', async () => {
        const onClose = vi.fn();
        const { container } = render(Modal, {
            props: { open: true, title: 'X' },
            events: { close: onClose },
        });
        await fireEvent.keyDown(container.querySelector('.backdrop')!, { key: 'Escape' });
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('dispatches close on backdrop click but not on inner click', async () => {
        const onClose = vi.fn();
        const { container } = render(Modal, {
            props: { open: true, title: 'X' },
            events: { close: onClose },
        });
        await fireEvent.click(container.querySelector('.modal')!);
        expect(onClose).not.toHaveBeenCalled();
        await fireEvent.click(container.querySelector('.backdrop')!);
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('locks body scroll while open and restores on close', async () => {
        const { rerender } = render(Modal, { props: { open: true, title: 'X' } });
        expect(document.body.style.overflow).toBe('hidden');
        await rerender({ open: false, title: 'X' });
        expect(document.body.style.overflow).toBe('');
    });

    it('restores body scroll on destroy even if never explicitly closed', () => {
        const { unmount } = render(Modal, { props: { open: true, title: 'X' } });
        expect(document.body.style.overflow).toBe('hidden');
        unmount();
        expect(document.body.style.overflow).toBe('');
    });
});
