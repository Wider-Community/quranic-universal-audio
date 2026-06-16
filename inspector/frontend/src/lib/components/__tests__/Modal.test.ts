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

    // The backdrop portals to `document.body` (escaping ancestor stacking
    // contexts), so it lives in `baseElement`, not the render `container`.
    it('renders nothing when closed', () => {
        const { baseElement } = render(Modal, { props: { open: false, title: 'X' } });
        expect(baseElement.querySelector('.modal')).toBeNull();
    });

    it('renders the title and a close button when open', () => {
        const { baseElement } = render(Modal, { props: { open: true, title: 'Pick reciter' } });
        const title = baseElement.querySelector('.modal-title');
        expect(title?.textContent).toBe('Pick reciter');
        expect(baseElement.querySelector('.modal-close')).not.toBeNull();
    });

    it('dispatches close on the close button click', async () => {
        const onClose = vi.fn();
        const { baseElement } = render(Modal, {
            props: { open: true, title: 'X' },
            events: { close: onClose },
        });
        await fireEvent.click(baseElement.querySelector('.modal-close')!);
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('dispatches close on Escape', async () => {
        const onClose = vi.fn();
        const { baseElement } = render(Modal, {
            props: { open: true, title: 'X' },
            events: { close: onClose },
        });
        await fireEvent.keyDown(baseElement.querySelector('.backdrop')!, { key: 'Escape' });
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('dispatches close on backdrop click but not on inner click', async () => {
        const onClose = vi.fn();
        const { baseElement } = render(Modal, {
            props: { open: true, title: 'X' },
            events: { close: onClose },
        });
        await fireEvent.click(baseElement.querySelector('.modal')!);
        expect(onClose).not.toHaveBeenCalled();
        await fireEvent.click(baseElement.querySelector('.backdrop')!);
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
