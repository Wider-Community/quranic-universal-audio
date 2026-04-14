/**
 * Validation helpers: refresh, no-op stubs, and index fixup utilities.
 *
 * Wave 8a.2: ValidationPanel.svelte owns accordion rendering reactively via
 * the $segValidation store. renderValidationPanel and the capture/restore
 * state helpers have been removed; see git history if needed.
 */

import { fetchJson } from '../../lib/api';
import { segValidation } from '../../lib/stores/segments/validation';
import type { SegValidateResponse } from '../../types/api';
import type { SegValAutoFix } from '../../types/domain';
import { applyFiltersAndRender } from '../filters';
import { dom,state } from '../state';

// ---------------------------------------------------------------------------
// refreshValidation -- re-fetch validation data and update store
// ---------------------------------------------------------------------------

export async function refreshValidation(): Promise<void> {
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;
    try {
        const valData = await fetchJson<SegValidateResponse>(`/api/seg/validate/${reciter}`);
        // Wave 8a.2: ValidationPanel.svelte subscribes to segValidation store
        // reactively. Open-state is preserved inside the component (no capture/restore
        // needed). Direct state assignment kept for legacy imperative consumers that
        // still read state.segValidation.
        segValidation.set(valData);
        state.segValidation = valData;
        // Wave 7: applyFiltersAndRender notifies stores so the {#each} re-renders.
        applyFiltersAndRender();
        if (state._segSavedPreviewState) {
            const saved = state._segSavedPreviewState;
            state._segSavedPreviewState = null;
            requestAnimationFrame(() => { dom.segListEl.scrollTop = saved.scrollTop; });
        }
    } catch (e) {
        console.error('Error refreshing validation:', e);
    }
}

// ---------------------------------------------------------------------------
// invalidateLoadedErrorCards / refreshOpenAccordionCards
// ---------------------------------------------------------------------------

// Wave 8a.2: ValidationPanel.svelte owns the DOM for validation accordions.
// These functions are kept as stubs so call sites in edit/split.ts, edit/merge.ts,
// edit/delete.ts continue to compile. Svelte's reactive {#each} re-renders
// automatically when segValidation.update(v => v) is called by the fixup helpers.

export function invalidateLoadedErrorCards(): void {
    // No-op: ValidationPanel.svelte re-derives from $segValidation reactively.
    // Open-state is component-local and is not forcibly reset here.
}

export function refreshOpenAccordionCards(): void {
    // No-op: ValidationPanel.svelte re-renders via {#each} when $segValidation changes.
    // The _fixupValIndicesFor* helpers call segValidation.update(v => v) which triggers
    // the reactive update automatically.
}

// ---------------------------------------------------------------------------
// Validation index fixup helpers
// ---------------------------------------------------------------------------

/**
 * Index-fixup target: an item carrying an index at a specific key. The
 * callback may read or mutate `item[key]` (number). Used with `seg_index` on
 * single-index categories and `target_seg_index` on `auto_fix` descriptors.
 */
type ValIndexedItem<K extends string> = { [P in K]: number };
type ValFixupFn = <K extends string>(item: ValIndexedItem<K>, key: K) => void;

function _forEachValItem(chapter: number, fn: ValFixupFn): void {
    if (!state.segValidation) return;
    for (const cat of state._VAL_SINGLE_INDEX_CATS) {
        const arr = state.segValidation[cat];
        if (!Array.isArray(arr)) continue;
        for (const item of arr as Array<{ chapter: number; seg_index?: number }>) {
            if (item.chapter === chapter && typeof item.seg_index === 'number') {
                fn(item as ValIndexedItem<'seg_index'>, 'seg_index');
            }
        }
    }
    const mw = state.segValidation.missing_words;
    if (mw) {
        for (const item of mw) {
            if (item.chapter !== chapter) continue;
            if (item.seg_indices) {
                for (let i = 0; i < item.seg_indices.length; i++) {
                    const idx = item.seg_indices[i];
                    if (idx == null) continue;
                    const wrapped: ValIndexedItem<'seg_index'> = { seg_index: idx };
                    fn(wrapped, 'seg_index');
                    item.seg_indices[i] = wrapped.seg_index;
                }
            }
            // B03: historically only re-indexed when `auto_fix` existed. Covered
            // here by design: items without `auto_fix` have no `target_seg_index`
            // to re-index. If the contract ever grows another indexed field on
            // `missing_words` rows directly, add a row in the bug log first.
            if (item.auto_fix) fn(item.auto_fix as ValIndexedItem<'target_seg_index'> & SegValAutoFix, 'target_seg_index');
        }
    }
}

export function _fixupValIndicesForSplit(chapter: number, splitIndex: number): void {
    _forEachValItem(chapter, <K extends string>(item: ValIndexedItem<K>, key: K) => {
        if (item[key] > splitIndex) item[key] = (item[key] + 1) as ValIndexedItem<K>[K];
    });
    segValidation.update(v => v); // notify subscribers of in-place mutation
}

export function _fixupValIndicesForMerge(chapter: number, keptIndex: number, consumedIndex: number): void {
    const maxIdx = Math.max(keptIndex, consumedIndex);
    _forEachValItem(chapter, <K extends string>(item: ValIndexedItem<K>, key: K) => {
        if (item[key] === consumedIndex) item[key] = keptIndex as ValIndexedItem<K>[K];
        else if (item[key] > maxIdx) item[key] = (item[key] - 1) as ValIndexedItem<K>[K];
    });
    segValidation.update(v => v); // notify subscribers of in-place mutation
}

export function _fixupValIndicesForDelete(chapter: number, deletedIndex: number): void {
    _forEachValItem(chapter, <K extends string>(item: ValIndexedItem<K>, key: K) => {
        if (item[key] === deletedIndex) item[key] = -1 as ValIndexedItem<K>[K];
        else if (item[key] > deletedIndex) item[key] = (item[key] - 1) as ValIndexedItem<K>[K];
    });
    segValidation.update(v => v); // notify subscribers of in-place mutation
}
