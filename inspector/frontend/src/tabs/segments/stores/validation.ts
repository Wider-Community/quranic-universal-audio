/**
 * Segments tab — validation data store.
 *
 * Validation data store for the segments tab.
 *
 * Shape: single `SegValidateResponse | null`.
 *
 * In-place mutation pattern: `_fixupValIndicesFor*` helpers mutate arrays
 * inside the store value in-place. After mutation, callers MUST call
 * `segValidation.update(v => v)` to notify subscribers.
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
