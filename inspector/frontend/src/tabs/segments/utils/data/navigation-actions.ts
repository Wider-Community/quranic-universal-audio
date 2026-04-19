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
    flashSegmentIndices,
    pendingScrollTop,
    savedFilterView,
    targetSegmentIndex,
} from '../../stores/navigation';
import { playStatusText, segListElement } from '../../stores/playback';
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

    _flashAndScrollTo(segIndex);

    if (fromFilterView) {
        _showBackToResultsBanner();
    }
}

/** Drive the post-jump scroll-into-view + 2s highlight through stores.
 *  SegmentRow reactively picks up both signals. */
function _flashAndScrollTo(segIndex: number): void {
    targetSegmentIndex.set(segIndex);
    flashSegmentIndices.update((s) => {
        const next = new Set(s);
        next.add(segIndex);
        return next;
    });
    setTimeout(() => {
        flashSegmentIndices.update((s) => {
            const next = new Set(s);
            next.delete(segIndex);
            return next;
        });
    }, 2000);
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
        playStatusText.set(`Could not locate boundary segments for missing verse ${verseKey}.`);
        return;
    }

    if (indices.length === 1) {
        // Single-row case: use targetSegmentIndex so SegmentRow scrolls itself
        // into view (no DOM query here).
        targetSegmentIndex.set(indices[0]!);
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
        for (const idx of indices) nextSet.add(idx);
        return nextSet;
    });
    setTimeout(() => {
        flashSegmentIndices.update((s) => {
            const nextSet = new Set(s);
            for (const idx of indices) nextSet.delete(idx);
            return nextSet;
        });
    }, 2000);

    if (prev && next) {
        playStatusText.set(`Missing verse ${verseKey} is between #${prev.index} and #${next.index}.`);
    } else if (prev) {
        playStatusText.set(`Missing verse ${verseKey} is after #${prev.index}.`);
    } else if (next) {
        playStatusText.set(`Missing verse ${verseKey} is before #${next.index}.`);
    }

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
        _flashAndScrollTo(seg.index);
        return;
    }
    playStatusText.set(`No segment found for verse ${verseKey}.`);
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
