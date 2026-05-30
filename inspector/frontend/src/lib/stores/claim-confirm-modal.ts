/**
 * Claim-confirm modal open/close state.
 *
 * Claiming a reciter for review is a deliberate action (you hold one claim at
 * a time), so it goes through a confirm step instead of firing immediately.
 * The modal is a single root-mounted component (see `App.svelte`) opened
 * imperatively from every claim entry point: the inline `ClaimButton`, the
 * edit-affordance popover, and the dashboard reciter modal. Centralizing here
 * keeps one claim path.
 */

import { writable } from 'svelte/store';

interface ClaimConfirmState {
    open: boolean;
    /** Reciter slug to claim on confirm. */
    slug: string | null;
    /** Invoked after a successful claim — typically a reciter-task refresh. */
    onClaimed: (() => void) | null;
}

export const claimConfirmModal = writable<ClaimConfirmState>({
    open: false,
    slug: null,
    onClaimed: null,
});

export interface OpenClaimConfirmOpts {
    onClaimed?: (() => void) | null;
}

export function openClaimConfirm(slug: string, opts: OpenClaimConfirmOpts = {}): void {
    claimConfirmModal.set({
        open: true,
        slug,
        onClaimed: opts.onClaimed ?? null,
    });
}

export function closeClaimConfirm(): void {
    claimConfirmModal.update((s) => ({ ...s, open: false }));
}
