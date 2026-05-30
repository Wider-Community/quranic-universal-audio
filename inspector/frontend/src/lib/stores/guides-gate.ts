/**
 * Open/closed state for the first-edit guide onboarding modal.
 *
 * Lives in `lib/` (cross-tab) because the lib-level `editGate` action opens it
 * when a blocked click carries `viewReason === 'guides_unread'`. The modal
 * component itself lives in `tabs/segments` (it knows about the guides) and
 * subscribes here — a clean tab→lib dependency.
 *
 * `mode` distinguishes the two ways the modal is shown:
 *   - `gate`   — blocking: the user tried to edit before reading the guides.
 *   - `browse` — voluntary: opened from the "Guides" entry point to read ahead.
 * Both render the same checklist; only the framing copy differs.
 */

import { writable } from 'svelte/store';

export type GuidesGateMode = 'gate' | 'browse';

export interface GuidesGateState {
    open: boolean;
    mode: GuidesGateMode;
}

export const guidesGate = writable<GuidesGateState>({ open: false, mode: 'gate' });

/** Open the modal (default `gate` — the blocking first-edit path). */
export function openGuidesGate(mode: GuidesGateMode = 'gate'): void {
    guidesGate.set({ open: true, mode });
}

export function closeGuidesGate(): void {
    guidesGate.update((s) => ({ ...s, open: false }));
}
