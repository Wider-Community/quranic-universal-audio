import { render, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
    claimConfirmModal,
    closeClaimConfirm,
    openClaimConfirm,
} from '../../stores/claim-confirm-modal';
import { currentUser } from '../../stores/current-user';
import ClaimConfirmModal from '../ClaimConfirmModal.svelte';

const claimMock = vi.fn((_slug: string) => Promise.resolve({} as never));

vi.mock('../../api/claims-client', () => ({
    claim: (slug: string) => claimMock(slug),
}));
vi.mock('../../api/reciter-task', () => ({
    refreshReciterTask: vi.fn(() => Promise.resolve(null)),
}));
vi.mock('../../../tabs/dashboard/stores/catalog-data', () => ({
    loadCatalog: vi.fn(() => Promise.resolve()),
}));
vi.mock('../../stores/current-user', async () => {
    const { writable } = await import('svelte/store');
    const store = writable({
        login: 'me',
        hf_user_id: 'u-1',
        role: 'contributor',
        active_claim: null,
        active_claims: [],
        dev_mode: false,
        capabilities: [],
        guides_read: [],
    });
    return { currentUser: store, loadCurrentUser: vi.fn(() => Promise.resolve()) };
});

function setUser(overrides: Record<string, unknown>) {
    currentUser.update((u) => ({ ...u, ...overrides }));
}

beforeEach(() => {
    claimMock.mockClear();
    setUser({ role: 'contributor', active_claim: null });
});

afterEach(() => {
    closeClaimConfirm();
    claimConfirmModal.set({ open: false, slug: null, onClaimed: null });
});

describe('ClaimConfirmModal', () => {
    it('renders the confirm copy and calls claim() on Confirm', async () => {
        const { container, getByText } = render(ClaimConfirmModal);
        openClaimConfirm('reciter-x');

        const confirm = await waitFor(() => getByText('Confirm'));
        expect(container.textContent).toContain('Claiming this reciter');
        confirm.click();
        await waitFor(() => expect(claimMock).toHaveBeenCalledWith('reciter-x'));
    });

    it('Cancel closes without claiming', async () => {
        const { getByText } = render(ClaimConfirmModal);
        openClaimConfirm('reciter-x');

        const cancel = await waitFor(() => getByText('Cancel'));
        cancel.click();
        expect(get(claimConfirmModal).open).toBe(false);
        expect(claimMock).not.toHaveBeenCalled();
    });

    it('shows the warn variant (no Confirm) when a contributor holds another claim', async () => {
        setUser({ active_claim: 'other-slug' });
        const { container, queryByText } = render(ClaimConfirmModal);
        openClaimConfirm('reciter-x');

        await waitFor(() => expect(container.textContent).toContain('one reciter at a time'));
        expect(queryByText('Confirm')).toBeNull();
    });

    it('owner with an existing claim still sees the confirm (multi-claim exempt)', async () => {
        setUser({ role: 'owner', active_claim: 'other-slug' });
        const { getByText } = render(ClaimConfirmModal);
        openClaimConfirm('reciter-x');

        await waitFor(() => expect(getByText('Confirm')).toBeTruthy());
    });
});
