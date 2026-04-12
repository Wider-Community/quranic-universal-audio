/**
 * Jump-to-segment, jump-to-verse, missing verse context, and filter view save/restore.
 */

import { state, dom } from './state.js';
import { parseSegRef } from './references.js';
import { getChapterSegments, onSegChapterChange } from './data.js';
import { applyFiltersAndRender, renderFilterBar, updateFilterBarControls } from './filters.js';

export async function jumpToSegment(chapter, segIndex) {
    const fromFilterView = !!state._segSavedFilterView;
    if (fromFilterView) {
        state.segActiveFilters = [];
        renderFilterBar();
        updateFilterBarControls();
    }

    if (dom.segChapterSelect.value !== String(chapter)) {
        dom.segChapterSelect.value = String(chapter);
        if (state.segChapterSS) state.segChapterSS.refresh();
        await onSegChapterChange();
    } else if (fromFilterView) {
        applyFiltersAndRender();
    }

    const row = dom.segListEl.querySelector(`.seg-row[data-seg-index="${segIndex}"]`);
    if (row) {
        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        row.classList.add('playing');
        setTimeout(() => row.classList.remove('playing'), 2000);
    }

    if (fromFilterView) {
        _showBackToResultsBanner();
    }
}

export function _parseVerseFromKey(verseKey) {
    const parts = (verseKey || '').split(':');
    if (parts.length < 2) return null;
    const verse = parseInt(parts[1], 10);
    return Number.isFinite(verse) ? verse : null;
}

export function findMissingVerseBoundarySegments(chapter, verseKey) {
    const targetVerse = _parseVerseFromKey(verseKey);
    if (!targetVerse) return { prev: null, next: null, targetVerse: null, covered: false };

    const segs = getChapterSegments(chapter);
    let prev = null;
    let prevVerse = -Infinity;
    let next = null;
    let nextVerse = Infinity;

    for (const seg of segs) {
        const parsed = parseSegRef(seg.matched_ref);
        if (!parsed) continue;

        if (parsed.ayah_from <= targetVerse && targetVerse <= parsed.ayah_to) {
            return { prev: seg, next: seg, targetVerse, covered: true };
        }

        if (parsed.ayah_to < targetVerse && parsed.ayah_to > prevVerse) {
            prev = seg;
            prevVerse = parsed.ayah_to;
        }
        if (parsed.ayah_from > targetVerse && parsed.ayah_from < nextVerse) {
            next = seg;
            nextVerse = parsed.ayah_from;
        }
    }

    return { prev, next, targetVerse, covered: false };
}

export async function jumpToMissingVerseContext(chapter, verseKey) {
    const targetVerse = _parseVerseFromKey(verseKey);
    if (!targetVerse) {
        await jumpToVerse(chapter, verseKey);
        return;
    }

    const hasFilterView = state.segActiveFilters.some(f => f.value !== null) || !!dom.segVerseSelect.value;
    if (hasFilterView) {
        state._segSavedFilterView = {
            filters: JSON.parse(JSON.stringify(state.segActiveFilters)),
            chapter: dom.segChapterSelect.value,
            verse: dom.segVerseSelect.value,
            scrollTop: dom.segListEl.scrollTop,
        };
    }

    if (dom.segChapterSelect.value !== String(chapter)) {
        dom.segChapterSelect.value = String(chapter);
        if (state.segChapterSS) state.segChapterSS.refresh();
        await onSegChapterChange();
    }

    if (hasFilterView) {
        state.segActiveFilters = [];
        renderFilterBar();
        updateFilterBarControls();
    }
    if (dom.segVerseSelect.value) {
        dom.segVerseSelect.value = '';
    }
    applyFiltersAndRender();

    const { prev, next, covered } = findMissingVerseBoundarySegments(chapter, verseKey);
    if (covered && prev) {
        await jumpToSegment(chapter, prev.index);
        return;
    }

    const rows = [];
    if (prev) {
        const row = dom.segListEl.querySelector(`.seg-row[data-seg-chapter="${chapter}"][data-seg-index="${prev.index}"]`);
        if (row) rows.push(row);
    }
    if (next && (!prev || next.index !== prev.index)) {
        const row = dom.segListEl.querySelector(`.seg-row[data-seg-chapter="${chapter}"][data-seg-index="${next.index}"]`);
        if (row) rows.push(row);
    }

    if (rows.length === 0) {
        dom.segPlayStatus.textContent = `Could not locate boundary segments for missing verse ${verseKey}.`;
        return;
    }

    if (rows.length === 1) {
        rows[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
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
    } else {
        dom.segPlayStatus.textContent = `Missing verse ${verseKey} is before #${next.index}.`;
    }

    if (hasFilterView) {
        _showBackToResultsBanner();
    }
}

export async function jumpToVerse(chapter, verseKey) {
    if (dom.segChapterSelect.value !== String(chapter)) {
        dom.segChapterSelect.value = String(chapter);
        if (state.segChapterSS) state.segChapterSS.refresh();
        await onSegChapterChange();
    }
    if (!state.segAllData) return;
    const parts = verseKey.split(':');
    const prefix = parts.length >= 2 ? `${parts[0]}:${parts[1]}:` : verseKey;
    const seg = state.segAllData.segments.find(s =>
        s.chapter === parseInt(chapter) && s.matched_ref && s.matched_ref.startsWith(prefix)
    );
    if (seg) {
        const row = dom.segListEl.querySelector(`.seg-row[data-seg-index="${seg.index}"]`);
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

export function _showBackToResultsBanner() {
    dom.segListEl.querySelector('.seg-back-banner')?.remove();
    const banner = document.createElement('div');
    banner.className = 'seg-back-banner';
    banner.innerHTML = '<button class="btn btn-sm seg-back-btn">\u2190 Back to filter results</button>';
    banner.querySelector('.seg-back-btn').addEventListener('click', _restoreFilterView);
    dom.segListEl.insertBefore(banner, dom.segListEl.firstChild);
}

export function _restoreFilterView() {
    if (!state._segSavedFilterView) return;
    const saved = state._segSavedFilterView;
    state._segSavedFilterView = null;

    state.segActiveFilters = saved.filters;
    renderFilterBar();
    updateFilterBarControls();

    if (saved.chapter !== dom.segChapterSelect.value) {
        dom.segChapterSelect.value = saved.chapter;
        if (state.segChapterSS) state.segChapterSS.refresh();
    }
    dom.segVerseSelect.value = saved.verse;

    applyFiltersAndRender();

    requestAnimationFrame(() => {
        dom.segListEl.scrollTop = saved.scrollTop;
    });
}
