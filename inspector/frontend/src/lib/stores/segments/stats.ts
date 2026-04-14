/**
 * Segments tab — stats data store.
 *
 * Promotes `state.segStatsData` (previously a plain field on the `state`
 * object) to a Svelte writable store so StatsPanel.svelte can subscribe
 * reactively and render charts without imperative DOM manipulation.
 *
 * Shape: single `SegStatsResponse | null` (provisional per S2-D11).
 *
 * Bridge: SegmentsTab.svelte syncs the store back to `state.segStatsData`
 * via a `$:` reactive statement so imperative callers continue working.
 *
 * Write sites (Wave 8b, 2026-04-14):
 *   - SegmentsTab.svelte (onReciterChange) → setStats()
 *   - SegmentsTab.svelte (clearPerReciterState) → clearStats()
 *   - segments/data.ts (onSegReciterChange) → setStats() / clearStats()
 *   - segments/data.ts (clearSegDisplay) → clearStats()
 */

import { writable } from 'svelte/store';

import type { SegStatsResponse } from '../../../types/api';

/** Stats data for the currently-loaded reciter, or null if none loaded. */
export const segStats = writable<SegStatsResponse | null>(null);

/** Set stats data (e.g. after fetching /api/seg/stats). Only called with valid
 *  (non-error) responses — callers must check `.error` before calling. */
export function setStats(data: SegStatsResponse): void {
    segStats.set(data);
}

/** Clear stats data (e.g. on reciter change / clear). */
export function clearStats(): void {
    segStats.set(null);
}
