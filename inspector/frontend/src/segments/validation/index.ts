/**
 * Validation panel rendering and index fixup helpers.
 * Renders accordion panels for each validation category.
 */

import { fetchJson } from '../../lib/api';
import {
    type AccordionOpenState,
    capturePanelOpenState,
    collapseSiblingDetails,
    restorePanelOpenState,
} from '../../shared/accordion';
import type { SegValidateResponse } from '../../types/api';
import type {
    SegValAnyItem,
    SegValAudioBleedingItem,
    SegValAutoFix,
    SegValBoundaryAdjItem,
    SegValCrossVerseItem,
    SegValFailedItem,
    SegValLowConfidenceItem,
    SegValMissingVerseItem,
    SegValMissingWordsItem,
    SegValMuqattaatItem,
    SegValQalqalaItem,
    SegValRepetitionItem,
    SegValStructuralErrorItem,
} from '../../types/domain';
import { applyFiltersAndRender } from '../filters';
import { jumpToMissingVerseContext,jumpToSegment, jumpToVerse } from '../navigation';
import { dom,state } from '../state';
import { renderCategoryCards } from './error-cards';

// ---------------------------------------------------------------------------
// captureValPanelState / restoreValPanelState — thin wrappers over
// shared/accordion helpers, kept for call-site compatibility.
// ---------------------------------------------------------------------------

export type ValPanelState = AccordionOpenState;

export function captureValPanelState(targetEl: HTMLElement): ValPanelState {
    return capturePanelOpenState(targetEl);
}

export function restoreValPanelState(targetEl: HTMLElement, st: ValPanelState): void {
    restorePanelOpenState(targetEl, st);
}

// ---------------------------------------------------------------------------
// _collapseAccordionExcept — thin wrapper over shared/accordion helper.
// ---------------------------------------------------------------------------

export function _collapseAccordionExcept(exceptDetails: HTMLDetailsElement): void {
    collapseSiblingDetails(exceptDetails);
}

// ---------------------------------------------------------------------------
// renderValidationPanel
// ---------------------------------------------------------------------------

/**
 * Per-category descriptor used by the accordion-rendering loop. The `items`
 * field is the narrowed array for the specific validation category; the
 * callbacks read/return strings and are invoked with the matching item type.
 *
 * `SegValAnyItem` is used as the outer `<I>` constraint so we can keep the
 * descriptor list itself homogeneously typed; each row narrows `I` at its
 * literal site.
 */
interface ValCategoryDescriptor<I extends SegValAnyItem> {
    name: string;
    items: I[];
    type: string;
    countClass: string;
    btnClass: string | ((item: I) => string);
    getLabel: (item: I) => string;
    getTitle: (item: I) => string;
    onClick: (item: I) => void;
    isQalqala?: boolean;
}

/** Mutable-open accordion `<details>` that carries cached category metadata. */
interface ValDetailsElement extends HTMLDetailsElement {
    _valCatType?: string;
    _valCatItems?: SegValAnyItem[];
}

/** Context-toggle button instrumented by `addContextToggle` in error-cards. */
interface ValCtxToggleButton extends HTMLButtonElement {
    _isContextShown?: () => boolean;
    _showContext?: () => void;
}

export function renderValidationPanel(
    data: SegValidateResponse | null,
    chapter: number | null = null,
    targetEl: HTMLElement = dom.segValidationEl,
    label: string | null = null,
): void {
    targetEl.innerHTML = '';
    if (!data) { targetEl.hidden = true; return; }

    const matchChapter = <T extends { chapter: number }>(arr: T[] | undefined): T[] =>
        chapter === null ? (arr ?? []) : (arr ?? []).filter((i) => i.chapter === chapter);

    const failed: SegValFailedItem[] = matchChapter(data.failed);
    const mv: SegValMissingVerseItem[] = matchChapter(data.missing_verses);
    const mw: SegValMissingWordsItem[] = matchChapter(data.missing_words);
    const errs: SegValStructuralErrorItem[] = matchChapter(data.errors ?? data.structural_errors);
    const low_confidence: SegValLowConfidenceItem[] = matchChapter(data.low_confidence);
    const ba: SegValBoundaryAdjItem[] = matchChapter(data.boundary_adj);
    const cv: SegValCrossVerseItem[] = matchChapter(data.cross_verse);
    const ab: SegValAudioBleedingItem[] = matchChapter(data.audio_bleeding);
    const rep: SegValRepetitionItem[] = matchChapter(data.repetitions);
    const muqattaat: SegValMuqattaatItem[] = matchChapter(data.muqattaat);
    const qalqala: SegValQalqalaItem[] = matchChapter(data.qalqala);

    const hasAny =
        errs.length > 0 || mv.length > 0 || mw.length > 0 ||
        failed.length > 0 || low_confidence.length > 0 || ba.length > 0 ||
        cv.length > 0 || ab.length > 0 || rep.length > 0 ||
        muqattaat.length > 0 || qalqala.length > 0;
    if (!hasAny) {
        targetEl.hidden = true;
        return;
    }
    targetEl.hidden = false;

    if (label) {
        const labelEl = document.createElement('div');
        labelEl.className = 'val-section-label';
        labelEl.textContent = label;
        targetEl.appendChild(labelEl);
    }

    // Heterogeneous descriptor list — each entry narrows the item type at its
    // literal site; we render them uniformly through `renderOne` below.
    const categories: ReadonlyArray<ValCategoryDescriptor<SegValAnyItem>> = [
        ({
            name: 'Failed Alignments', items: failed, type: 'failed', countClass: 'has-errors',
            getLabel: (i: SegValFailedItem) => `${i.chapter}:#${i.seg_index}`,
            getTitle: (i: SegValFailedItem) => `${i.time}`,
            btnClass: 'val-error',
            onClick: (i: SegValFailedItem) => jumpToSegment(i.chapter, i.seg_index),
        } as ValCategoryDescriptor<SegValFailedItem>) as ValCategoryDescriptor<SegValAnyItem>,
        ({
            name: 'Missing Verses', items: mv, type: 'missing_verses', countClass: 'has-errors',
            getLabel: (i: SegValMissingVerseItem) => i.verse_key,
            getTitle: (i: SegValMissingVerseItem) => i.msg ?? '',
            btnClass: 'val-error',
            onClick: (i: SegValMissingVerseItem) => jumpToMissingVerseContext(i.chapter, i.verse_key),
        } as ValCategoryDescriptor<SegValMissingVerseItem>) as ValCategoryDescriptor<SegValAnyItem>,
        ({
            name: 'Missing Words', items: mw, type: 'missing_words', countClass: 'has-errors',
            getLabel: (i: SegValMissingWordsItem) => {
                const indices = i.seg_indices || [];
                return indices.length > 0 ? `${i.verse_key} #${indices.join('/#')}` : i.verse_key;
            },
            getTitle: (i: SegValMissingWordsItem) => i.msg ?? '',
            btnClass: 'val-error',
            onClick: (i: SegValMissingWordsItem) => {
                const indices = i.seg_indices || [];
                const first = indices[0];
                if (first != null) jumpToSegment(i.chapter, first);
                else jumpToVerse(i.chapter, i.verse_key);
            },
        } as ValCategoryDescriptor<SegValMissingWordsItem>) as ValCategoryDescriptor<SegValAnyItem>,
        ({
            name: 'Structural Errors', items: errs, type: 'errors', countClass: 'has-errors',
            getLabel: (i: SegValStructuralErrorItem) => i.verse_key,
            getTitle: (i: SegValStructuralErrorItem) => i.msg,
            btnClass: 'val-error',
            onClick: (i: SegValStructuralErrorItem) => jumpToVerse(i.chapter, i.verse_key),
        } as ValCategoryDescriptor<SegValStructuralErrorItem>) as ValCategoryDescriptor<SegValAnyItem>,
        ({
            name: 'Detected Repetitions', items: rep, type: 'repetitions', countClass: 'val-rep-count',
            getLabel: (i: SegValRepetitionItem) => i.display_ref || i.ref,
            getTitle: (i: SegValRepetitionItem) => i.text,
            btnClass: 'val-rep',
            onClick: (i: SegValRepetitionItem) => jumpToSegment(i.chapter, i.seg_index),
        } as ValCategoryDescriptor<SegValRepetitionItem>) as ValCategoryDescriptor<SegValAnyItem>,
        ({
            name: 'Low Confidence', items: low_confidence, type: 'low_confidence', countClass: 'has-warnings',
            getLabel: (i: SegValLowConfidenceItem) => i.ref,
            getTitle: (i: SegValLowConfidenceItem) => `${(i.confidence * 100).toFixed(1)}%`,
            btnClass: (i: SegValLowConfidenceItem) => i.confidence < 0.60 ? 'val-conf-low' : 'val-conf-mid',
            onClick: (i: SegValLowConfidenceItem) => jumpToSegment(i.chapter, i.seg_index),
        } as ValCategoryDescriptor<SegValLowConfidenceItem>) as ValCategoryDescriptor<SegValAnyItem>,
        ({
            name: 'May Require Boundary Adjustment', items: ba, type: 'boundary_adj', countClass: 'has-warnings',
            getLabel: (i: SegValBoundaryAdjItem) => i.ref,
            getTitle: (i: SegValBoundaryAdjItem) => i.verse_key,
            btnClass: 'val-conf-mid',
            onClick: (i: SegValBoundaryAdjItem) => jumpToSegment(i.chapter, i.seg_index),
        } as ValCategoryDescriptor<SegValBoundaryAdjItem>) as ValCategoryDescriptor<SegValAnyItem>,
        ({
            name: 'Cross-verse', items: cv, type: 'cross_verse', countClass: 'val-cross-count',
            getLabel: (i: SegValCrossVerseItem) => i.ref,
            getTitle: () => '',
            btnClass: 'val-cross',
            onClick: (i: SegValCrossVerseItem) => jumpToSegment(i.chapter, i.seg_index),
        } as ValCategoryDescriptor<SegValCrossVerseItem>) as ValCategoryDescriptor<SegValAnyItem>,
        ({
            name: 'Audio Bleeding', items: ab, type: 'audio_bleeding', countClass: 'has-warnings',
            getLabel: (i: SegValAudioBleedingItem) => `${i.entry_ref}\u2192${i.matched_verse}`,
            getTitle: (i: SegValAudioBleedingItem) =>
                `audio ${i.entry_ref} contains segment matching ${i.ref} (${i.time})`,
            btnClass: 'val-bleed',
            onClick: (i: SegValAudioBleedingItem) => jumpToSegment(i.chapter, i.seg_index),
        } as ValCategoryDescriptor<SegValAudioBleedingItem>) as ValCategoryDescriptor<SegValAnyItem>,
        ({
            name: 'Muqatta\u02bcat', items: muqattaat, type: 'muqattaat', countClass: 'val-cross-count',
            getLabel: (i: SegValMuqattaatItem) => i.ref,
            getTitle: () => '',
            btnClass: 'val-cross',
            onClick: (i: SegValMuqattaatItem) => jumpToSegment(i.chapter, i.seg_index),
        } as ValCategoryDescriptor<SegValMuqattaatItem>) as ValCategoryDescriptor<SegValAnyItem>,
        ({
            name: 'Qalqala', items: qalqala, type: 'qalqala', countClass: 'val-cross-count',
            isQalqala: true,
            getLabel: (i: SegValQalqalaItem) => i.ref,
            getTitle: () => '',
            btnClass: 'val-cross',
            onClick: (i: SegValQalqalaItem) => jumpToSegment(i.chapter, i.seg_index),
        } as ValCategoryDescriptor<SegValQalqalaItem>) as ValCategoryDescriptor<SegValAnyItem>,
    ];

    const QALQALA_LETTERS_ORDER: ReadonlyArray<string> = ['\u0642', '\u0637', '\u0628', '\u062c', '\u062f'];

    categories.forEach((cat) => {
        if (!cat.items || cat.items.length === 0) return;

        const isLowConf: boolean = cat.type === 'low_confidence';
        const isQalqala: boolean = !!cat.isQalqala;
        const LC_DEFAULT: number = state._lcDefaultThreshold;

        let lcThreshold: number = LC_DEFAULT;
        let activeQalqalaLetter: string | null = null;
        let qalqalaEndOfVerse: boolean = false;
        const getVisibleItems = (): SegValAnyItem[] => {
            if (isLowConf) {
                return (cat.items as SegValLowConfidenceItem[])
                    .filter((i) => (i.confidence * 100) < lcThreshold)
                    .sort((a, b) => a.confidence - b.confidence);
            }
            if (isQalqala) {
                let items = cat.items as SegValQalqalaItem[];
                if (activeQalqalaLetter) items = items.filter((i) => i.qalqala_letter === activeQalqalaLetter);
                if (qalqalaEndOfVerse) items = items.filter((i) => i.end_of_verse === true);
                return items;
            }
            return cat.items;
        };

        const details = document.createElement('details') as ValDetailsElement;
        details.setAttribute('data-category', cat.type);
        details._valCatType = cat.type;
        details._valCatItems = cat.items;
        const summary = document.createElement('summary');
        const countForSummary: number = isLowConf
            ? (cat.items as SegValLowConfidenceItem[]).filter((i) => (i.confidence * 100) < LC_DEFAULT).length
            : cat.items.length;
        summary.innerHTML = `${cat.name} <span class="val-count ${cat.countClass}" data-lc-count>${countForSummary}</span>`;

        details.appendChild(summary);

        let sliderRow: HTMLDivElement | null = null;
        if (isLowConf) {
            sliderRow = document.createElement('div');
            sliderRow.className = 'lc-slider-row';
            sliderRow.hidden = true;
            sliderRow.innerHTML = `<label class="lc-slider-label">Show confidence &lt; <span class="lc-slider-val">${LC_DEFAULT}%</span></label><input type="range" class="lc-slider" min="50" max="99" step="1" value="${LC_DEFAULT}">`;
            details.appendChild(sliderRow);
        }

        let qalqalaFilterRow: HTMLDivElement | null = null;
        if (isQalqala) {
            const row = document.createElement('div');
            qalqalaFilterRow = row;
            row.className = 'lc-slider-row qalqala-filter-row';
            row.hidden = true;
            const filterLabel = document.createElement('span');
            filterLabel.className = 'lc-slider-label';
            filterLabel.textContent = 'Filter by letter:';
            row.appendChild(filterLabel);
            QALQALA_LETTERS_ORDER.forEach((letter) => {
                if (!(cat.items as SegValQalqalaItem[]).some((i) => i.qalqala_letter === letter)) return;
                const btn = document.createElement('button');
                btn.className = 'val-btn val-cross qalqala-letter-btn';
                btn.textContent = letter;
                btn.title = `Show only segments ending with ${letter}`;
                btn.setAttribute('data-letter', letter);
                btn.addEventListener('click', () => {
                    const countEl = summary.querySelector('[data-lc-count]');
                    if (activeQalqalaLetter === letter) {
                        activeQalqalaLetter = null;
                        btn.classList.remove('active');
                    } else {
                        activeQalqalaLetter = letter;
                        row.querySelectorAll('.qalqala-letter-btn').forEach((b) => b.classList.remove('active'));
                        btn.classList.add('active');
                    }
                    const visible = getVisibleItems();
                    if (countEl) countEl.textContent = String(visible.length);
                    if (state._cardRenderRafId) { cancelAnimationFrame(state._cardRenderRafId); state._cardRenderRafId = null; }
                    cardsDiv.innerHTML = '';
                    renderCategoryCards(cat.type, visible, cardsDiv);
                    requestAnimationFrame(_updateCtxAllBtn);
                });
                row.appendChild(btn);
            });
            const eovBtn = document.createElement('button');
            eovBtn.className = 'val-btn val-cross qalqala-eov-btn';
            eovBtn.textContent = 'End of verse';
            eovBtn.title = 'Show only segments that end at a verse boundary';
            eovBtn.addEventListener('click', () => {
                qalqalaEndOfVerse = !qalqalaEndOfVerse;
                eovBtn.classList.toggle('active', qalqalaEndOfVerse);
                const visible = getVisibleItems();
                const countEl = summary.querySelector('[data-lc-count]');
                if (countEl) countEl.textContent = String(visible.length);
                if (state._cardRenderRafId) { cancelAnimationFrame(state._cardRenderRafId); state._cardRenderRafId = null; }
                cardsDiv.innerHTML = '';
                renderCategoryCards(cat.type, visible, cardsDiv);
            });
            row.appendChild(eovBtn);
            details.appendChild(row);
        }

        const itemsDiv = document.createElement('div');
        itemsDiv.className = 'val-items';
        itemsDiv.hidden = true;
        if (isQalqala) itemsDiv.style.display = 'none';

        const rebuildButtons = (items: SegValAnyItem[]): void => {
            itemsDiv.innerHTML = '';
            items.forEach((issue) => {
                const btn = document.createElement('button');
                const cls: string = typeof cat.btnClass === 'function' ? cat.btnClass(issue) : cat.btnClass;
                btn.className = `val-btn ${cls}`;
                btn.textContent = cat.getLabel(issue);
                btn.title = cat.getTitle(issue) || '';
                btn.addEventListener('click', () => cat.onClick(issue));
                itemsDiv.appendChild(btn);
            });
        };
        rebuildButtons(getVisibleItems());
        details.appendChild(itemsDiv);

        const cardsDiv = document.createElement('div');
        cardsDiv.className = 'val-cards-container';
        cardsDiv.hidden = true;

        const _ctxDefaultShown: boolean = (state._accordionContext?.[cat.type] ?? 'hidden') !== 'hidden';
        const ctxAllRow = document.createElement('div');
        ctxAllRow.className = 'val-ctx-all-row';
        ctxAllRow.hidden = true;
        const ctxAllBtn = document.createElement('button');
        ctxAllBtn.className = 'val-action-btn val-action-btn-muted';
        ctxAllBtn.textContent = _ctxDefaultShown ? 'Hide All Context' : 'Show All Context';
        ctxAllRow.appendChild(ctxAllBtn);
        details.appendChild(ctxAllRow);

        function _updateCtxAllBtn(): void {
            const anyShown = [...cardsDiv.querySelectorAll<ValCtxToggleButton>('.val-ctx-toggle-btn')]
                .some((b) => b._isContextShown?.() === true);
            ctxAllBtn.textContent = anyShown ? 'Hide All Context' : 'Show All Context';
        }
        ctxAllBtn.addEventListener('click', () => {
            const allBtns = [...cardsDiv.querySelectorAll<ValCtxToggleButton>('.val-ctx-toggle-btn')];
            const anyShown = allBtns.some((b) => b._isContextShown?.() === true);
            allBtns.forEach((b) => {
                if (anyShown && b._isContextShown?.() === true) b.click();
                else if (!anyShown && b._showContext && b._isContextShown?.() !== true) b.click();
            });
            _updateCtxAllBtn();
        });

        details.appendChild(cardsDiv);

        if (isLowConf && sliderRow) {
            const sliderEl = sliderRow.querySelector<HTMLInputElement>('.lc-slider');
            const sliderValEl = sliderRow.querySelector<HTMLElement>('.lc-slider-val');
            const countEl = summary.querySelector<HTMLElement>('[data-lc-count]');
            if (sliderEl) {
                sliderEl.addEventListener('input', () => {
                    lcThreshold = parseInt(sliderEl.value);
                    if (sliderValEl) sliderValEl.textContent = `${lcThreshold}%`;
                    const visible = getVisibleItems();
                    if (countEl) countEl.textContent = String(visible.length);
                    rebuildButtons(visible);
                    if (state._cardRenderRafId) { cancelAnimationFrame(state._cardRenderRafId); state._cardRenderRafId = null; }
                    cardsDiv.innerHTML = '';
                    renderCategoryCards(cat.type, visible, cardsDiv);
                });
            }
        }

        details.addEventListener('toggle', () => {
            if (details.open) {
                _collapseAccordionExcept(details);
                if (sliderRow) sliderRow.hidden = false;
                if (qalqalaFilterRow) qalqalaFilterRow.hidden = false;
                if (!isQalqala) itemsDiv.hidden = false;
                const visible = getVisibleItems();
                if (!isQalqala) rebuildButtons(visible);
                renderCategoryCards(cat.type, visible, cardsDiv);
                cardsDiv.hidden = false;
                ctxAllRow.hidden = false;
                requestAnimationFrame(_updateCtxAllBtn);
            } else {
                if (state._cardRenderRafId) { cancelAnimationFrame(state._cardRenderRafId); state._cardRenderRafId = null; }
                if (sliderRow) sliderRow.hidden = true;
                if (qalqalaFilterRow) qalqalaFilterRow.hidden = true;
                itemsDiv.hidden = true;
                cardsDiv.innerHTML = '';
                cardsDiv.hidden = true;
                ctxAllRow.hidden = true;
            }
        });

        targetEl.appendChild(details);
    });
}

// ---------------------------------------------------------------------------
// refreshValidation -- re-fetch validation data and re-render panels
// ---------------------------------------------------------------------------

export async function refreshValidation(): Promise<void> {
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;
    try {
        const globalState = captureValPanelState(dom.segValidationGlobalEl);
        const chState = captureValPanelState(dom.segValidationEl);
        state.segValidation = await fetchJson<SegValidateResponse>(`/api/seg/validate/${reciter}`);
        const ch = dom.segChapterSelect.value ? parseInt(dom.segChapterSelect.value) : null;
        if (ch !== null) {
            renderValidationPanel(state.segValidation, null, dom.segValidationGlobalEl, 'All Chapters');
            renderValidationPanel(state.segValidation, ch, dom.segValidationEl, `Chapter ${ch}`);
            restoreValPanelState(dom.segValidationGlobalEl, globalState);
            restoreValPanelState(dom.segValidationEl, chState);
        } else {
            dom.segValidationGlobalEl.hidden = true;
            dom.segValidationGlobalEl.innerHTML = '';
            renderValidationPanel(state.segValidation, null, dom.segValidationEl);
            restoreValPanelState(dom.segValidationEl, chState);
        }
        // Wave 7: both branches collapse to applyFiltersAndRender — the
        // shim notifies stores so the {#each} re-renders. Stage-1 used
        // renderSegList for the segDisplayedSegments-only path; today the
        // derived `displayedSegments` re-fires on segAllData.update().
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

export function invalidateLoadedErrorCards(): void {
    document.querySelectorAll<HTMLDetailsElement>('details[data-category]').forEach((details) => {
        if (details.open) details.open = false;
    });
}

export function refreshOpenAccordionCards(): void {
    document.querySelectorAll<ValDetailsElement>('details[data-category]').forEach((details) => {
        if (!details.open) return;
        const cardsDiv = details.querySelector<HTMLElement>('.val-cards-container');
        const type = details._valCatType;
        const items = details._valCatItems;
        if (!cardsDiv || !items || !type) return;
        renderCategoryCards(type, items, cardsDiv);
    });
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
}

export function _fixupValIndicesForMerge(chapter: number, keptIndex: number, consumedIndex: number): void {
    const maxIdx = Math.max(keptIndex, consumedIndex);
    _forEachValItem(chapter, <K extends string>(item: ValIndexedItem<K>, key: K) => {
        if (item[key] === consumedIndex) item[key] = keptIndex as ValIndexedItem<K>[K];
        else if (item[key] > maxIdx) item[key] = (item[key] - 1) as ValIndexedItem<K>[K];
    });
}

export function _fixupValIndicesForDelete(chapter: number, deletedIndex: number): void {
    _forEachValItem(chapter, <K extends string>(item: ValIndexedItem<K>, key: K) => {
        if (item[key] === deletedIndex) item[key] = -1 as ValIndexedItem<K>[K];
        else if (item[key] > deletedIndex) item[key] = (item[key] - 1) as ValIndexedItem<K>[K];
    });
}
