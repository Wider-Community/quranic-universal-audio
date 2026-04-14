/**
 * Segments tab — save-preview visibility store.
 *
 * Tracks whether the save-preview panel (#seg-save-preview) is visible.
 * Imperative code in segments/save.ts calls showPreview() / hidePreview()
 * alongside its existing DOM manipulation so SavePreview.svelte can bind
 * the `hidden` attribute reactively.
 *
 * Store granularity provisional through Wave 9 (S2-D11). Preview content
 * (batches, summary stats) continues to be rendered imperatively by
 * segments/history/rendering.ts; Wave 10 will migrate that.
 *
 * Write sites (Wave 9, 2026-04-14):
 *   - segments/save.ts (showSavePreview) → showPreview()
 *   - segments/save.ts (hideSavePreview) → hidePreview()
 */

import { writable } from 'svelte/store';

/** True while #seg-save-preview is visible. */
export const savePreviewVisible = writable<boolean>(false);

/** Show the save-preview panel (call alongside setting dom.segSavePreview.hidden = false). */
export function showPreview(): void {
    savePreviewVisible.set(true);
}

/** Hide the save-preview panel (call alongside setting dom.segSavePreview.hidden = true). */
export function hidePreview(): void {
    savePreviewVisible.set(false);
}
