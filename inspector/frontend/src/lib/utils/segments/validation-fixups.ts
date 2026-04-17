import type { SegValAutoFix } from '../../../types/domain';
import { state } from '../../segments-state';
import { segValidation } from '../../stores/segments/validation';

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
            if (item.auto_fix) fn(item.auto_fix as ValIndexedItem<'target_seg_index'> & SegValAutoFix, 'target_seg_index');
        }
    }
}

export function _fixupValIndicesForSplit(chapter: number, splitIndex: number): void {
    _forEachValItem(chapter, <K extends string>(item: ValIndexedItem<K>, key: K) => {
        if (item[key] > splitIndex) item[key] = (item[key] + 1) as ValIndexedItem<K>[K];
    });
    segValidation.update(v => v);
}

export function _fixupValIndicesForMerge(chapter: number, keptIndex: number, consumedIndex: number): void {
    const maxIdx = Math.max(keptIndex, consumedIndex);
    _forEachValItem(chapter, <K extends string>(item: ValIndexedItem<K>, key: K) => {
        if (item[key] === consumedIndex) item[key] = keptIndex as ValIndexedItem<K>[K];
        else if (item[key] > maxIdx) item[key] = (item[key] - 1) as ValIndexedItem<K>[K];
    });
    segValidation.update(v => v);
}

export function _fixupValIndicesForDelete(chapter: number, deletedIndex: number): void {
    _forEachValItem(chapter, <K extends string>(item: ValIndexedItem<K>, key: K) => {
        if (item[key] === deletedIndex) item[key] = -1 as ValIndexedItem<K>[K];
        else if (item[key] > deletedIndex) item[key] = (item[key] - 1) as ValIndexedItem<K>[K];
    });
    segValidation.update(v => v);
}

export function invalidateLoadedErrorCards(): void {
    // No-op: ValidationPanel.svelte re-derives from $segValidation reactively.
}

export function refreshOpenAccordionCards(): void {
    // No-op: ValidationPanel.svelte re-renders via {#each} when $segValidation changes.
}
