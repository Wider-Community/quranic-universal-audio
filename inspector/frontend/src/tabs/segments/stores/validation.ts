/**
 * Segments tab — validation data store.
 *
 * Shape: single `SegValidateResponse | null`.
 *
 * Items carry `segment_uid` for stable identity through structural edits.
 * Stale items (uid absent from live state) are filtered before render by
 * `filterStaleIssues` in ValidationPanel.
 */

import { derived, writable } from 'svelte/store';

import type { SegValidateResponse } from '../../../lib/types/generated/schemas';

/** Validation data for the currently-loaded reciter, or null if none loaded. */
export const segValidation = writable<SegValidateResponse | null>(null);

/** Server-supplied split-group closures keyed by root uid. Read by accordion
 *  cards to expand a split chain without subscribing to historyData. Empty
 *  map until the first validate response lands. */
export const splitGroupIndex = derived(
    segValidation,
    ($v) => ($v?.split_group_index ?? {}) as Record<string, string[]>,
);

// ---- UI state persistence (in-memory) ----
export const valUiOpenCategory = writable<string | null>(null);
export const valUiLcThreshold = writable<number | null>(null);
export const valUiScrollTop = writable<number>(0);
export const valUiMeasuredCardHeight = writable<number | null>(null);

/** True iff a validation accordion is open. Accordion view and chapter-cards
 *  view are mutually exclusive — `SegmentsTab` gates `<SegmentsList>` on
 *  `!$accordionViewActive`. Derived (not a writable) so external mutations
 *  can't desync it from the source of truth. */
export const accordionViewActive = derived(
    valUiOpenCategory,
    ($c) => $c !== null,
);

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
