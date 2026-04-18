/**
 * Jump-to-segment, jump-to-verse, missing verse context, and filter view
 * save/restore.
 *
 * The back-to-results banner is rendered by Navigation.svelte (subscribed
 * to `backBannerVisible` derived from `savedFilterView`).
 * `_showBackToResultsBanner` is kept as a no-op compatibility shim (stored
 * filter view is already in the store); `_restoreFilterView` re-applies the
 * saved filters/chapter/verse.
 */

import { get } from 'svelte/store';

import {
    segAllData,
    segChapterSS,
    selectedChapter,
    selectedReciter,
    selectedVerse,
} from '../../stores/segments/chapter';
import { activeFilters as activeFiltersStore } from '../../stores/segments/filters';
import { savedFilterView as savedFilterViewStore } from '../../stores/segments/navigation';
import { playStatusText, segListElement } from '../../stores/segments/playback';
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
        const ss = get(segChapterSS);
        if (ss) ss.refresh();
        await loadChapterData(get(selectedReciter), chStr);
    }
}

export async function jumpToSegment(chapter: number | string, segIndex: number): Promise<void> {
    const fromFilterView = get(savedFilterViewStore) !== null;
    if (fromFilterView) {
        activeFiltersStore.set([]);
    }

    const chStr = String(chapter);
    const chapterChanged = get(selectedChapter) !== chStr;
    if (chapterChanged) {
        await _ensureChapter(chapter);
    } else if (fromFilterView) {
        applyFiltersAndRender();
    }

    const listEl = get(segListElement);
    const row = listEl?.querySelector<HTMLElement>(`.seg-row[data-seg-index="${segIndex}"]`) ?? null;
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

    const curFilters = get(activeFiltersStore);
    const hasFilterView = curFilters.some(f => f.value !== null) || !!get(selectedVerse);
    if (hasFilterView) {
        const listEl = get(segListElement);
        savedFilterViewStore.set({
            filters: JSON.parse(JSON.stringify(curFilters)),
            chapter: get(selectedChapter),
            verse: get(selectedVerse),
            scrollTop: listEl?.scrollTop ?? 0,
        });
    }

    await _ensureChapter(chapter);

    if (hasFilterView) {
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

    const listEl = get(segListElement);
    const rows: HTMLElement[] = [];
    if (prev && listEl) {
        const row = listEl.querySelector<HTMLElement>(`.seg-row[data-seg-chapter="${chapter}"][data-seg-index="${prev.index}"]`);
        if (row) rows.push(row);
    }
    if (next && listEl && (!prev || next.index !== prev.index)) {
        const row = listEl.querySelector<HTMLElement>(`.seg-row[data-seg-chapter="${chapter}"][data-seg-index="${next.index}"]`);
        if (row) rows.push(row);
    }

    if (rows.length === 0) {
        playStatusText.set(`Could not locate boundary segments for missing verse ${verseKey}.`);
        return;
    }

    if (rows.length === 1) {
        rows[0]!.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } else if (listEl) {
        const top = Math.min(...rows.map(r => r.offsetTop));
        const bottom = Math.max(...rows.map(r => r.offsetTop + r.offsetHeight));
        const targetTop = Math.max(0, ((top + bottom) / 2) - (listEl.clientHeight / 2));
        listEl.scrollTo({ top: targetTop, behavior: 'smooth' });
    }

    rows.forEach(r => r.classList.add('playing'));
    setTimeout(() => rows.forEach(r => r.classList.remove('playing')), 2000);

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
        const listEl = get(segListElement);
        const row = listEl?.querySelector<HTMLElement>(`.seg-row[data-seg-index="${seg.index}"]`) ?? null;
        if (row) {
            row.scrollIntoView({ behavior: 'smooth', block: 'center' });
            row.classList.add('playing');
            setTimeout(() => row.classList.remove('playing'), 2000);
        }
        return;
    }
    playStatusText.set(`No segment found for verse ${verseKey}.`);
}

// ---------------------------------------------------------------------------
// Filter view save / restore (Go To -> Back navigation)
// ---------------------------------------------------------------------------

/**
 * No-op compatibility shim — the banner reacts directly to `savedFilterView`
 * changes via Navigation.svelte's `backBannerVisible` derived store. Kept as
 * an exported symbol so existing callers compile.
 */
export function _showBackToResultsBanner(): void {
    // Intentional no-op — see module docstring.
}

export function _restoreFilterView(): void {
    const saved = get(savedFilterViewStore);
    if (!saved) return;
    savedFilterViewStore.set(null);

    activeFiltersStore.set([...saved.filters]);

    if (saved.chapter !== get(selectedChapter)) {
        selectedChapter.set(saved.chapter);
        const ss = get(segChapterSS);
        if (ss) ss.refresh();
    }
    selectedVerse.set(saved.verse);

    applyFiltersAndRender();

    requestAnimationFrame(() => {
        const listEl = get(segListElement);
        if (listEl) listEl.scrollTop = saved.scrollTop;
    });
}
