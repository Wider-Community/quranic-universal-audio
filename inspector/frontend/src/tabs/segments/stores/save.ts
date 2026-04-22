/**
 * Segments tab — save-preview store.
 *
 * `savePreviewData` writable carries the full preview payload so
 * SavePreview.svelte can render summary stats + batch cards reactively.
 */

import { writable } from 'svelte/store';

import type { EditOp, HistoryBatch } from '../../../lib/types/domain';
import type { SavedChainsSnapshot } from '../types/segments';

// ---------------------------------------------------------------------------
// SavePreviewData — preview payload shape (mirrors buildSavePreviewData return)
// ---------------------------------------------------------------------------

export interface SavePreviewBatch {
    batch_id: null;
    saved_at_utc: null;
    chapter: number;
    save_mode: 'full_replace' | 'patch';
    operations: EditOp[];
}

export interface SavePreviewSummary {
    total_operations: number;
    total_batches: number;
    chapters_edited: number;
    verses_edited: number;
    op_counts: Record<string, number>;
    fix_kind_counts: Record<string, number>;
}

export interface SavePreviewData {
    batches: SavePreviewBatch[];
    summary: SavePreviewSummary;
    warningChapters: number[];
}

// ---------------------------------------------------------------------------
// Stores
// ---------------------------------------------------------------------------

/** True while #seg-save-preview is visible. */
export const savePreviewVisible = writable<boolean>(false);

/** Label on the main Save button. Typically 'Save' or a transient message
 *  like 'Saving...' / 'Saved N changes'. */
export const saveButtonLabel = writable<string>('Save');

/** Full preview payload. Non-null while preview is showing. */
export const savePreviewData = writable<SavePreviewData | null>(null);

/** Snapshot of the split-chain state captured around showSavePreview so
 *  hideSavePreview can restore it exactly. `null` when no preview is active. */
export const savedChains = writable<SavedChainsSnapshot | null>(null);

/** Saved scroll position of the segments list around showSavePreview. `null`
 *  when no preview is active. */
export const savedPreviewScroll = writable<number | null>(null);

// ---------------------------------------------------------------------------
// Mutators
// ---------------------------------------------------------------------------

/** Show the save-preview panel and publish its data to the store. */
export function showPreview(): void {
    savePreviewVisible.set(true);
}

/** Hide the save-preview panel. */
export function hidePreview(): void {
    savePreviewVisible.set(false);
}

/** Publish preview payload so SavePreview.svelte can render reactively. */
export function setSavePreviewData(data: SavePreviewData): void {
    savePreviewData.set(data);
}

/** Clear preview payload on hide. */
export function clearSavePreviewData(): void {
    savePreviewData.set(null);
}

// Type re-export so callers don't need to import from domain.ts separately.
export type { HistoryBatch };
