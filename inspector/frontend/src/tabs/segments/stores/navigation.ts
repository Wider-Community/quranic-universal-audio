/**
 * Segments tab — saved filter view (for "Back to results" banner).
 *
 * `backBannerVisible` derived is an alias for "view is saved" — consumed by
 * Navigation.svelte to conditionally render the back-banner.
 *
 * Cross-cutting: Navigation.svelte subscribes to `activeFilters` and clears
 * `savedFilterView` when filters become non-empty. Other writers (reciter
 * change, explicit "back" click, explicit "clear filters") clear it directly
 * via `.set(null)`.
 */

import { derived, writable } from 'svelte/store';

import type { SegActiveFilter } from './filters';

/** Saved UI snapshot so Navigation.svelte can restore a filter + scroll view. */
export interface SegSavedFilterView {
    filters: SegActiveFilter[];
    chapter: string;
    verse: string;
    scrollTop: number;
}

/** Writable — the saved view, or null when no "back to results" is available. */
export const savedFilterView = writable<SegSavedFilterView | null>(null);

/** Derived boolean: whether to render the back-to-results banner. */
export const backBannerVisible = derived(
    savedFilterView,
    ($s) => $s !== null,
);

/** A (chapter, index) pair — reused by `targetSegmentIndex` and
 *  `flashSegmentIndices` so same-index rows across chapters never collide.
 *  Chapter is always a concrete number (the targeted chapter); callers that
 *  only know "the current chapter" resolve it at the call site. */
export interface ChapterIndexRef {
    chapter: number;
    index: number;
}

/** Build the canonical `"chapter:index"` string key. Kept as a helper so the
 *  shape matches the row-registry key format exactly. */
export function chapterIndexKey(chapter: number, index: number): string {
    return `${chapter}:${index}`;
}

/** The displayed-segment target that should be scrolled into view. Only the
 *  main-list SegmentRow instance reacts to this — accordion / history /
 *  preview twins leave it alone. Cleared to null by SegmentRow after the
 *  match + scrollIntoView. Chapter-scoped so a same-index row in another
 *  chapter (accordion with chapter=null) can't match the wrong row. */
export const targetSegmentIndex = writable<ChapterIndexRef | null>(null);

/** Set of `"chapter:index"` keys that should have the transient flash
 *  (visual highlight after jump). Cleared by setTimeout after ~2 seconds.
 *  SegmentRow ORs this with isPlaying to drive the `.playing` class.
 *  Chapter-scoped so a flash for chapter 5 doesn't also light chapter 3
 *  rows that happen to be mounted in accordions. */
export const flashSegmentIndices = writable<Set<string>>(new Set());

/** Drop every flash key belonging to `chapter`. Called by structural
 *  mutations (split/merge/delete) after reindex so a flash keyed by the
 *  pre-mutation index doesn't linger on the wrong row post-reindex. */
export function clearFlashForChapter(chapter: number): void {
    const prefix = `${chapter}:`;
    flashSegmentIndices.update((s) => {
        for (const k of [...s]) {
            if (k.startsWith(prefix)) s.delete(k);
        }
        return s;
    });
}

/** One-shot scroll-top target for the seg-list container. Set by
 *  _restoreFilterView, consumed + cleared by SegmentsList's afterUpdate. */
export const pendingScrollTop = writable<number | null>(null);
