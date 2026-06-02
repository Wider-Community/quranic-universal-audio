/**
 * Open state for the accordion guide modal, lifted out of `ValidationPanel`
 * into a store so the guide can be opened from anywhere — the per-accordion
 * `?` button AND the onboarding `GuidesGateModal` (which must open guides for
 * reciters that don't surface that accordion at all).
 *
 * A single `AccordionGuideModal` host (mounted in `SegmentsTab`) renders
 * whatever is set here; `opener` is the element to restore focus to on close.
 */

import { writable } from 'svelte/store';

export interface GuideModalState {
    category: string;
    opener: HTMLElement | null;
}

export const guideModal = writable<GuideModalState | null>(null);

/** Open the guide for `category`, remembering `opener` for focus restoration. */
export function openGuideModal(category: string, opener: HTMLElement | null = null): void {
    guideModal.set({ category, opener });
}

export function closeGuideModal(): void {
    guideModal.set(null);
}
