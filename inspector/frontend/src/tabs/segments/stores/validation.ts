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

// ---- UI state persistence (in-memory) ----
export const valUiOpenCategory = writable<string | null>(null);
export const valUiLcThreshold = writable<number | null>(null);
export const valUiScrollTop = writable<number>(0);
export const valUiMeasuredCardHeight = writable<number | null>(null);

/** Set validation data (e.g. after fetching /api/seg/validate). */
export function setValidation(data: SegValidateResponse): void {
    segValidation.set(data);
}

/** Clear validation data (e.g. on reciter change / clear). */
export function clearValidation(): void {
    segValidation.set(null);
    valUiOpenCategory.set(null);
    valUiScrollTop.set(0);
}
