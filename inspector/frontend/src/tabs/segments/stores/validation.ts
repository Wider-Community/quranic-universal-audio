/**
 * Segments tab — validation data store.
 *
 * Shape: single `SegValidateResponse | null`.
 *
 * Items carry `segment_uid` for stable identity through structural edits.
 * Stale items (uid absent from live state) are filtered before render by
 * `filterStaleIssues` in ValidationPanel.
 */

import { writable } from 'svelte/store';

import type { SegValidateResponse } from '../../../lib/types/api';

/** Validation data for the currently-loaded reciter, or null if none loaded. */
export const segValidation = writable<SegValidateResponse | null>(null);

/** Set validation data (e.g. after fetching /api/seg/validate). */
export function setValidation(data: SegValidateResponse): void {
    segValidation.set(data);
}

/** Clear validation data (e.g. on reciter change / clear). */
export function clearValidation(): void {
    segValidation.set(null);
}
