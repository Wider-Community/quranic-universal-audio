import { get } from 'svelte/store';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
    claimConfirmModal,
    closeClaimConfirm,
    openClaimConfirm,
} from '../claim-confirm-modal';

afterEach(() => {
    closeClaimConfirm();
    claimConfirmModal.set({ open: false, slug: null, onClaimed: null });
});

describe('claim-confirm-modal store', () => {
    it('opens with the given slug and defaults onClaimed to null', () => {
        openClaimConfirm('reciter-x');
        const s = get(claimConfirmModal);
        expect(s.open).toBe(true);
        expect(s.slug).toBe('reciter-x');
        expect(s.onClaimed).toBeNull();
    });

    it('carries the onClaimed callback through', () => {
        const cb = vi.fn();
        openClaimConfirm('reciter-y', { onClaimed: cb });
        expect(get(claimConfirmModal).onClaimed).toBe(cb);
    });

    it('close() flips open to false but keeps the slug for the close animation', () => {
        openClaimConfirm('reciter-z');
        closeClaimConfirm();
        const s = get(claimConfirmModal);
        expect(s.open).toBe(false);
        expect(s.slug).toBe('reciter-z');
    });
});
