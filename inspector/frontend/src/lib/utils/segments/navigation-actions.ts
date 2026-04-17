/**
 * Jump-to-segment, jump-to-verse, missing verse context, and filter view
 * save/restore.
 *
 * The back-to-results banner is rendered by Navigation.svelte (subscribed
 * to `backBannerVisible` derived from `savedFilterView`).
 * `_showBackToResultsBanner` mirrors `state._segSavedFilterView` into the
 * store so the banner appears; `_restoreFilterView` reverses the flow and
 * re-applies the saved filters/chapter/verse.
 */

import { get } from 'svelte/store';

import { dom, state } from '../../segments-state';
import {
    selectedChapter,
    selectedReciter,
    selectedVerse,
} from '../../stores/segments/chapter';
import { activeFilters as activeFiltersStore } from '../../stores/segments/filters';
import { savedFilterView as savedFilterViewStore } from '../../stores/segments/navigation';
import { loadChapterData } from './chapter-actions';
import { applyFiltersAndRender } from './filters-apply';
import {
    _parseVerseFromKey,
    findMissingVerseBoundarySegments,
} from './missing-verse-context';

// Re-export for callers that imported these from segments/navigation.
export { _parseVerseFromKey, findMissingVerseBoundarySegments };

async function _ensureChapter(chapter: number | string): Promise<void> {
    const chStr = String(chapter);
    if (get(selectedChapter) !== chStr) {
        selectedChapter.set(chStr);
        if (state.segChapterSS) state.segChapterSS.refresh();
        await loadChapterData(get(selectedReciter), chStr);
    }
}

export async function jumpToSegment(chapter: number | string, segIndex: number): Promise<void> {
    const fromFilterView = !!state._segSavedFilterView;
    if (fromFilterView) {
        state.segActiveFilters = [];
        activeFiltersStore.set([]);
    }

    const chStr = String(chapter);
    const chapterChanged = get(selectedChapter) !== chStr;
    if (chapterChanged) {
        await _ensureChapter(chapter);
    } else if (fromFilterView) {
        applyFiltersAndRender();
    }

    const row = dom.segListEl.querySelector<HTMLElement>(`.seg-row[data-seg-index="${segIndex}"]`);
    if (row) {
        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        row.classList.add('playing');
        setTimeout(() => row.classList.remove('playing'), 2000);
    }

    if (fromFilterView) {
        _showBackToResultsBanner();
    }
}

export async function jumpToMissingVerseContext(chapter: number | string, verseKey: string): Promise<void> {
    const targetVerse = _parseVerseFromKey(verseKey);
    if (!targetVerse) {
        await jumpToVerse(chapter, verseKey);
        return;
    }

    const hasFilterView = state.segActiveFilters.some(f => f.value !== null) || !!get(selectedVerse);
    if (hasFilterView) {
        state._segSavedFilterView = {
            filters: JSON.parse(JSON.stringify(state.segActiveFilters)),
            chapter: get(selectedChapter),
            verse: get(selectedVerse),
            scrollTop: dom.segListEl.scrollTop,
        };
    }

    await _ensureChapter(chapter);

    if (hasFilterView) {
        state.segActiveFilters = [];
        activeFiltersStore.set([]);
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

    const rows: HTMLElement[] = [];
    if (prev) {
        const row = dom.segListEl.querySelector<HTMLElement>(`.seg-row[data-seg-chapter="${chapter}"][data-seg-index="${prev.index}"]`);
        if (row) rows.push(row);
    }
    if (next && (!prev || next.index !== prev.index)) {
        const row = dom.segListEl.querySelector<HTMLElement>(`.seg-row[data-seg-chapter="${chapter}"][data-seg-index="${next.index}"]`);
        if (row) rows.push(row);
    }

    if (rows.length === 0) {
        dom.segPlayStatus.textContent = `Could not locate boundary segments for missing verse ${verseKey}.`;
        return;
    }

    if (rows.length === 1) {
        rows[0]!.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } else {
        const top = Math.min(...rows.map(r => r.offsetTop));
        const bottom = Math.max(...rows.map(r => r.offsetTop + r.offsetHeight));
        const targetTop = Math.max(0, ((top + bottom) / 2) - (dom.segListEl.clientHeight / 2));
        dom.segListEl.scrollTo({ top: targetTop, behavior: 'smooth' });
    }

    rows.forEach(r => r.classList.add('playing'));
    setTimeout(() => rows.forEach(r => r.classList.remove('playing')), 2000);

    if (prev && next) {
        dom.segPlayStatus.textContent = `Missing verse ${verseKey} is between #${prev.index} and #${next.index}.`;
    } else if (prev) {
        dom.segPlayStatus.textContent = `Missing verse ${verseKey} is after #${prev.index}.`;
    } else if (next) {
        dom.segPlayStatus.textContent = `Missing verse ${verseKey} is before #${next.index}.`;
    }

    if (hasFilterView) {
        _showBackToResultsBanner();
    }
}

export async function jumpToVerse(chapter: number | string, verseKey: string): Promise<void> {
    await _ensureChapter(chapter);
    if (!state.segAllData) return;
    const parts = verseKey.split(':');
    const prefix = parts.length >= 2 ? `${parts[0]}:${parts[1]}:` : verseKey;
    const chapterNum = typeof chapter === 'string' ? parseInt(chapter) : chapter;
    const seg = state.segAllData.segments.find(s =>
        s.chapter === chapterNum && s.matched_ref && s.matched_ref.startsWith(prefix)
    );
    if (seg) {
        const row = dom.segListEl.querySelector<HTMLElement>(`.seg-row[data-seg-index="${seg.index}"]`);
        if (row) {
            row.scrollIntoView({ behavior: 'smooth', block: 'center' });
            row.classList.add('playing');
            setTimeout(() => row.classList.remove('playing'), 2000);
        }
        return;
    }
    dom.segPlayStatus.textContent = `No segment found for verse ${verseKey}.`;
}

// ---------------------------------------------------------------------------
// Filter view save / restore (Go To -> Back navigation)
// ---------------------------------------------------------------------------

/**
 * Mirror `state._segSavedFilterView` into the `savedFilterView` store so
 * Navigation.svelte renders the banner.
 */
export function _showBackToResultsBanner(): void {
    if (!state._segSavedFilterView) return;
    savedFilterViewStore.set(state._segSavedFilterView);
}

export function _restoreFilterView(): void {
    if (!state._segSavedFilterView) return;
    const saved = state._segSavedFilterView;
    state._segSavedFilterView = null;
    savedFilterViewStore.set(null);

    state.segActiveFilters = saved.filters;
    activeFiltersStore.set([...saved.filters]);

    if (saved.chapter !== get(selectedChapter)) {
        selectedChapter.set(saved.chapter);
        if (state.segChapterSS) state.segChapterSS.refresh();
    }
    selectedVerse.set(saved.verse);

    applyFiltersAndRender();

    requestAnimationFrame(() => {
        dom.segListEl.scrollTop = saved.scrollTop;
    });
}
