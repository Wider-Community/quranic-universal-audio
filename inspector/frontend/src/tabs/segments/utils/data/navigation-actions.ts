/**
 * Jump-to-segment, jump-to-verse, missing verse context, and filter view
 * save/restore.
 *
 * The back-to-results banner is rendered by Navigation.svelte (subscribed
 * to `backBannerVisible` derived from `savedFilterView`).
 * `_restoreFilterView` re-applies the saved filters/chapter/verse.
 */

import { get } from 'svelte/store';

import {
    segAllData,
    selectedChapter,
    selectedReciter,
    selectedVerse,
} from '../../stores/chapter';
import { activeFilters } from '../../stores/filters';
import {
    chapterIndexKey,
    flashSegmentIndices,
    pendingScrollTop,
    savedFilterView,
    targetSegmentIndex,
} from '../../stores/navigation';
import { segListElement } from '../../stores/playback';
import { FLASH_DURATION_MS } from '../constants';
import {
    _parseVerseFromKey,
    findMissingVerseBoundarySegments,
} from '../validation/missing-verse-context';
import { loadChapterData } from './chapter-actions';
import { applyFiltersAndRender } from './filters-apply';

// Re-export for callers that imported these from segments/navigation.
export { _parseVerseFromKey, findMissingVerseBoundarySegments };

async function _ensureChapter(chapter: number | string): Promise<void> {
    const chStr = String(chapter);
    if (get(selectedChapter) !== chStr) {
        selectedChapter.set(chStr);
        await loadChapterData(get(selectedReciter), chStr);
    }
}

export async function jumpToSegment(chapter: number | string, segIndex: number): Promise<void> {
    const fromFilterView = get(savedFilterView) !== null;
    if (fromFilterView) {
        activeFilters.set([]);
    }

    const chStr = String(chapter);
    const chapterChanged = get(selectedChapter) !== chStr;
    if (chapterChanged) {
        await _ensureChapter(chapter);
    } else if (fromFilterView) {
        applyFiltersAndRender();
    }

    // `_ensureChapter` guarantees `selectedChapter === String(chapter)` by the
    // time we reach this line, so the main-list SegmentRow for (chapter,
    // segIndex) is mounted and will pick up the scroll target reactively.
    const chapterNum = typeof chapter === 'string' ? parseInt(chapter) : chapter;
    _flashAndScrollTo(chapterNum, segIndex);

    if (fromFilterView) {
        _showBackToResultsBanner();
    }
}

/** Drive the post-jump scroll-into-view + flash-highlight through stores.
 *  Only the main-list SegmentRow instance for the matching (chapter, index)
 *  reacts to `targetSegmentIndex`; any mounted twin (chapter, index) also
 *  flashes — desired UX so the accordion reflects the jump. */
function _flashAndScrollTo(chapter: number, segIndex: number): void {
    targetSegmentIndex.set({ chapter, index: segIndex });
    const flashKey = chapterIndexKey(chapter, segIndex);
    flashSegmentIndices.update((s) => {
        const next = new Set(s);
        next.add(flashKey);
        return next;
    });
    setTimeout(() => {
        flashSegmentIndices.update((s) => {
            const next = new Set(s);
            next.delete(flashKey);
            return next;
        });
    }, FLASH_DURATION_MS);
}

export async function jumpToMissingVerseContext(chapter: number | string, verseKey: string): Promise<void> {
    const targetVerse = _parseVerseFromKey(verseKey);
    if (!targetVerse) {
        await jumpToVerse(chapter, verseKey);
        return;
    }

    const curFilters = get(activeFilters);
    const hasFilterView = curFilters.some(f => f.value !== null) || !!get(selectedVerse);
    if (hasFilterView) {
        const listEl = get(segListElement);
        savedFilterView.set({
            filters: JSON.parse(JSON.stringify(curFilters)),
            chapter: get(selectedChapter),
            verse: get(selectedVerse),
            scrollTop: listEl?.scrollTop ?? 0,
        });
    }

    await _ensureChapter(chapter);

    if (hasFilterView) {
        activeFilters.set([]);
    }
    if (get(selectedVerse)) {
        selectedVerse.set('');
    }
    applyFiltersAndRender();

    const { prev, next, covered } = findMissingVerseBoundarySegments(chapter, verseKey);
    if (covered && prev) {
        await jumpToSegment(chapter, prev.index);
        return;
    }

    const listEl = get(segListElement);
    const indices: number[] = [];
    if (prev) indices.push(prev.index);
    if (next && (!prev || next.index !== prev.index)) indices.push(next.index);

    if (indices.length === 0) {
        return;
    }

    const chapterNum = typeof chapter === 'string' ? parseInt(chapter) : chapter;
    if (indices.length === 1) {
        // Single-row case: use targetSegmentIndex so SegmentRow scrolls itself
        // into view (no DOM query here).
        targetSegmentIndex.set({ chapter: chapterNum, index: indices[0]! });
    } else if (listEl) {
        // Two-row case: still need offsetTop arithmetic to center the scroll
        // between the two row midpoints. Residual DOM access is legit — Svelte
        // can't express "scroll to midpoint between two {#each} children".
        const rows: HTMLElement[] = [];
        for (const idx of indices) {
            const row = listEl.querySelector<HTMLElement>(`.seg-row[data-seg-chapter="${chapter}"][data-seg-index="${idx}"]`);
            if (row) rows.push(row);
        }
        if (rows.length > 0) {
            const top = Math.min(...rows.map(r => r.offsetTop));
            const bottom = Math.max(...rows.map(r => r.offsetTop + r.offsetHeight));
            const targetTop = Math.max(0, ((top + bottom) / 2) - (listEl.clientHeight / 2));
            listEl.scrollTo({ top: targetTop, behavior: 'smooth' });
        }
    }

    flashSegmentIndices.update((s) => {
        const nextSet = new Set(s);
        for (const idx of indices) nextSet.add(chapterIndexKey(chapterNum, idx));
        return nextSet;
    });
    setTimeout(() => {
        flashSegmentIndices.update((s) => {
            const nextSet = new Set(s);
            for (const idx of indices) nextSet.delete(chapterIndexKey(chapterNum, idx));
            return nextSet;
        });
    }, FLASH_DURATION_MS);

    if (hasFilterView) {
        _showBackToResultsBanner();
    }
}

export async function jumpToVerse(chapter: number | string, verseKey: string): Promise<void> {
    await _ensureChapter(chapter);
    const allData = get(segAllData);
    if (!allData) return;
    const parts = verseKey.split(':');
    const prefix = parts.length >= 2 ? `${parts[0]}:${parts[1]}:` : verseKey;
    const chapterNum = typeof chapter === 'string' ? parseInt(chapter) : chapter;
    const seg = allData.segments.find(s =>
        s.chapter === chapterNum && s.matched_ref && s.matched_ref.startsWith(prefix)
    );
    if (seg) {
        _flashAndScrollTo(chapterNum, seg.index);
    }
}

// ---------------------------------------------------------------------------
// Filter view save / restore (Go To -> Back navigation)
// ---------------------------------------------------------------------------

/**
 * No-op — the banner reacts directly to `savedFilterView` changes via
 * Navigation.svelte's `backBannerVisible` derived store.
 */
export function _showBackToResultsBanner(): void {
    // Intentional no-op.
}

export function _restoreFilterView(): void {
    const saved = get(savedFilterView);
    if (!saved) return;
    savedFilterView.set(null);

    activeFilters.set([...saved.filters]);

    if (saved.chapter !== get(selectedChapter)) {
        selectedChapter.set(saved.chapter);
    }
    selectedVerse.set(saved.verse);

    applyFiltersAndRender();

    // SegmentsList.afterUpdate consumes pendingScrollTop after the {#each}
    // reconciles, so the scroll happens once rows are in the DOM.
    pendingScrollTop.set(saved.scrollTop);
}
