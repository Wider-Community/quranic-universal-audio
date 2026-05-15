/**
 * Single-instance popover anchor store.
 *
 * The `editGate` action sets `{anchor, mode}` when it intercepts a click
 * from a non-editor; `EditAffordancePopover` (mounted once at app root)
 * subscribes and renders itself near the anchor element.
 */

import { writable } from 'svelte/store';

import type { EditingMode } from './editing-mode';

export interface EditPopoverState {
    anchor: HTMLElement;
    mode: EditingMode;
}

export const editPopover = writable<EditPopoverState | null>(null);

export function showEditPopover(anchor: HTMLElement, mode: EditingMode): void {
    editPopover.set({ anchor, mode });
}

export function hideEditPopover(): void {
    editPopover.set(null);
}
