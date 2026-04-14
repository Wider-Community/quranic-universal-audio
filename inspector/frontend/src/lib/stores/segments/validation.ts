/**
 * Segments tab — validation data store.
 *
 * Promotes `state.segValidation` (previously a plain field on the `state`
 * object) to a Svelte writable store so downstream consumers — primarily
 * SegmentsList.svelte's `missingWordSegIndices` derivation — can subscribe
 * reactively without the `void $displayedSegments` re-trigger workaround
 * (Wave 7a.1 NB-3 / Wave 8a prerequisite).
 *
 * Shape: single `SegValidateResponse | null` (provisional per S2-D11 —
 * store granularity may evolve through Wave 9 if individual categories need
 * independent subscriptions).
 *
 * Bridge: SegmentsTab.svelte syncs the store back to `state.segValidation`
 * via a `$:` reactive statement so that imperative callers (validation/
 * index.ts, segments/state.ts) continue working without modification.
 *
 * In-place mutation pattern: the `_fixupValIndicesFor*` helpers in
 * validation/index.ts mutate arrays inside the store value in-place.
 * After mutation, callers MUST call `segValidation.update(v => v)` to
 * notify subscribers (identity update — no structural copy needed).
 *
 * Wave 8a status (2026-04-14): initial promotion. Write sites:
 *   - SegmentsTab.svelte:249 (reciter load) → setValidation()
 *   - SegmentsTab.svelte:296 (clearPerReciterState) → clearValidation()
 *   - validation/index.ts:436 (refreshValidation) → setValidation()
 *   - validation/index.ts _fixupValIndicesFor* → segValidation.update(v => v)
 *   - SegmentsList.svelte — keys missingWordSegIndices derivation on
 *     $segValidation; removes `void $displayedSegments` dep trigger (D1
 *     memoization simplification).
 */

import { writable } from 'svelte/store';

import type { SegValidateResponse } from '../../../types/api';

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
