/**
 * Validation panel rendering and index fixup helpers.
 * Renders accordion panels for each validation category.
 */

import { state, dom } from './state.js';
import { getChapterSegments, getSegByChapterIndex } from './data.js';
import { renderSegList } from './rendering.js';
import { renderCategoryCards } from './error-cards.js';
import { applyFiltersAndRender } from './filters.js';
import { jumpToSegment, jumpToVerse, jumpToMissingVerseContext } from './navigation.js';
import { _ensureWaveformObserver } from './waveform.js';

// ---------------------------------------------------------------------------
// captureValPanelState / restoreValPanelState
// ---------------------------------------------------------------------------

export function captureValPanelState(targetEl) {
    const st = {};
    targetEl.querySelectorAll('details[data-category]').forEach(d => {
        st[d.getAttribute('data-category')] = { open: d.open };
    });
    return st;
}

export function restoreValPanelState(targetEl, st) {
    targetEl.querySelectorAll('details[data-category]').forEach(d => {
        const s = st[d.getAttribute('data-category')];
        if (s && s.open) d.open = true;
    });
}

// ---------------------------------------------------------------------------
// _collapseAccordionExcept
// ---------------------------------------------------------------------------

export function _collapseAccordionExcept(exceptDetails) {
    const panel = exceptDetails.closest('#seg-validation-global, #seg-validation') || exceptDetails.parentElement;
    panel.querySelectorAll('details[data-category]').forEach(d => {
        if (d === exceptDetails) return;
        if (d.open) d.open = false;
    });
}

// ---------------------------------------------------------------------------
// renderValidationPanel
// ---------------------------------------------------------------------------

export function renderValidationPanel(data, chapter = null, targetEl = dom.segValidationEl, label = null) {
    targetEl.innerHTML = '';
    if (!data) { targetEl.hidden = true; return; }

    let { errors: errs, missing_verses: mv, missing_words: mw, failed, low_confidence, boundary_adj: ba, cross_verse: cv, audio_bleeding: ab, repetitions: rep, muqattaat, qalqala } = data;

    if (chapter !== null) {
        errs           = (errs           || []).filter(i => i.chapter === chapter);
        mv             = (mv             || []).filter(i => i.chapter === chapter);
        mw             = (mw             || []).filter(i => i.chapter === chapter);
        failed         = (failed         || []).filter(i => i.chapter === chapter);
        low_confidence = (low_confidence || []).filter(i => i.chapter === chapter);
        ba             = (ba             || []).filter(i => i.chapter === chapter);
        cv             = (cv             || []).filter(i => i.chapter === chapter);
        ab             = (ab             || []).filter(i => i.chapter === chapter);
        rep            = (rep            || []).filter(i => i.chapter === chapter);
        muqattaat      = (muqattaat      || []).filter(i => i.chapter === chapter);
        qalqala        = (qalqala        || []).filter(i => i.chapter === chapter);
    }
    const hasAny = (errs && errs.length > 0) || (mv && mv.length > 0) || (mw && mw.length > 0)
        || (failed && failed.length > 0) || (low_confidence && low_confidence.length > 0) || (ba && ba.length > 0)
        || (cv && cv.length > 0) || (ab && ab.length > 0) || (rep && rep.length > 0)
        || (muqattaat && muqattaat.length > 0) || (qalqala && qalqala.length > 0);
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

    const isGlobal = chapter === null;

    const categories = [
        {
            name: 'Failed Alignments', items: failed, type: 'failed', countClass: 'has-errors',
            getLabel: i => `${i.chapter}:#${i.seg_index}`, getTitle: i => `${i.time}`, btnClass: 'val-error',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'Missing Verses', items: mv, type: 'missing_verses', countClass: 'has-errors',
            getLabel: i => i.verse_key, getTitle: i => i.msg, btnClass: 'val-error',
            onClick: i => jumpToMissingVerseContext(i.chapter, i.verse_key)
        },
        {
            name: 'Missing Words', items: mw, type: 'missing_words', countClass: 'has-errors',
            getLabel: i => {
                const indices = i.seg_indices || [];
                return indices.length > 0 ? `${i.verse_key} #${indices.join('/#')}` : i.verse_key;
            },
            getTitle: i => i.msg, btnClass: 'val-error',
            onClick: i => {
                const indices = i.seg_indices || [];
                if (indices.length > 0) jumpToSegment(i.chapter, indices[0]);
                else jumpToVerse(i.chapter, i.verse_key);
            }
        },
        {
            name: 'Structural Errors', items: errs, type: 'errors', countClass: 'has-errors',
            getLabel: i => i.verse_key, getTitle: i => i.msg, btnClass: 'val-error',
            onClick: i => jumpToVerse(i.chapter, i.verse_key)
        },
        {
            name: 'Detected Repetitions', items: rep, type: 'repetitions', countClass: 'val-rep-count',
            getLabel: i => i.display_ref || i.ref, getTitle: i => i.text, btnClass: 'val-rep',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'Low Confidence', items: low_confidence, type: 'low_confidence', countClass: 'has-warnings',
            getLabel: i => i.ref, getTitle: i => `${(i.confidence * 100).toFixed(1)}%`,
            btnClass: i => i.confidence < 0.60 ? 'val-conf-low' : 'val-conf-mid',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'May Require Boundary Adjustment', items: ba, type: 'boundary_adj', countClass: 'has-warnings',
            getLabel: i => i.ref, getTitle: i => i.verse_key, btnClass: 'val-conf-mid',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'Cross-verse', items: cv, type: 'cross_verse', countClass: 'val-cross-count',
            getLabel: i => i.ref, getTitle: () => '', btnClass: 'val-cross',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'Audio Bleeding', items: ab, type: 'audio_bleeding', countClass: 'has-warnings',
            getLabel: i => `${i.entry_ref}\u2192${i.matched_verse}`,
            getTitle: i => `audio ${i.entry_ref} contains segment matching ${i.ref} (${i.time})`,
            btnClass: 'val-bleed',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'Muqatta\u02bcat', items: muqattaat || [], type: 'muqattaat', countClass: 'val-cross-count',
            getLabel: i => i.ref, getTitle: () => '', btnClass: 'val-cross',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'Qalqala', items: qalqala || [], type: 'qalqala', countClass: 'val-cross-count',
            isQalqala: true,
            getLabel: i => i.ref, getTitle: () => '', btnClass: 'val-cross',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
    ];

    const QALQALA_LETTERS_ORDER = ['\u0642', '\u0637', '\u0628', '\u062c', '\u062f'];

    categories.forEach(cat => {
        if (!cat.items || cat.items.length === 0) return;

        const isLowConf = cat.type === 'low_confidence';
        const isQalqala = !!cat.isQalqala;
        const LC_DEFAULT = state._lcDefaultThreshold;

        let lcThreshold = LC_DEFAULT;
        let activeQalqalaLetter = null;
        const getVisibleItems = () => {
            if (isLowConf) return cat.items.filter(i => (i.confidence * 100) < lcThreshold).sort((a, b) => a.confidence - b.confidence);
            if (isQalqala && activeQalqalaLetter) return cat.items.filter(i => i.qalqala_letter === activeQalqalaLetter);
            return cat.items;
        };

        const details = document.createElement('details');
        details.setAttribute('data-category', cat.type);
        details._valCatType = cat.type;
        details._valCatItems = cat.items;
        const summary = document.createElement('summary');
        const countForSummary = isLowConf ? cat.items.filter(i => (i.confidence * 100) < LC_DEFAULT).length : cat.items.length;
        summary.innerHTML = `${cat.name} <span class="val-count ${cat.countClass}" data-lc-count>${countForSummary}</span>`;

        details.appendChild(summary);

        let sliderRow = null;
        if (isLowConf) {
            sliderRow = document.createElement('div');
            sliderRow.className = 'lc-slider-row';
            sliderRow.hidden = true;
            sliderRow.innerHTML = `<label class="lc-slider-label">Show confidence &lt; <span class="lc-slider-val">${LC_DEFAULT}%</span></label><input type="range" class="lc-slider" min="50" max="99" step="1" value="${LC_DEFAULT}">`;
            details.appendChild(sliderRow);
        }

        let qalqalaFilterRow = null;
        if (isQalqala) {
            qalqalaFilterRow = document.createElement('div');
            qalqalaFilterRow.className = 'lc-slider-row qalqala-filter-row';
            qalqalaFilterRow.hidden = true;
            const filterLabel = document.createElement('span');
            filterLabel.className = 'lc-slider-label';
            filterLabel.textContent = 'Filter by letter:';
            qalqalaFilterRow.appendChild(filterLabel);
            QALQALA_LETTERS_ORDER.forEach(letter => {
                if (!cat.items.some(i => i.qalqala_letter === letter)) return;
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
                        qalqalaFilterRow.querySelectorAll('.qalqala-letter-btn').forEach(b => b.classList.remove('active'));
                        btn.classList.add('active');
                    }
                    const visible = getVisibleItems();
                    if (countEl) countEl.textContent = visible.length;
                    if (state._cardRenderRafId) { cancelAnimationFrame(state._cardRenderRafId); state._cardRenderRafId = null; }
                    cardsDiv.innerHTML = '';
                    renderCategoryCards(cat.type, visible, cardsDiv);
                    requestAnimationFrame(_updateCtxAllBtn);
                });
                qalqalaFilterRow.appendChild(btn);
            });
            details.appendChild(qalqalaFilterRow);
        }

        const itemsDiv = document.createElement('div');
        itemsDiv.className = 'val-items';
        itemsDiv.hidden = true;
        if (isQalqala) itemsDiv.style.display = 'none';

        const rebuildButtons = (items) => {
            itemsDiv.innerHTML = '';
            items.forEach(issue => {
                const btn = document.createElement('button');
                const cls = typeof cat.btnClass === 'function' ? cat.btnClass(issue) : cat.btnClass;
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

        const _ctxDefaultShown = (state._accordionContext?.[cat.type] ?? 'hidden') !== 'hidden';
        const ctxAllRow = document.createElement('div');
        ctxAllRow.className = 'val-ctx-all-row';
        ctxAllRow.hidden = true;
        const ctxAllBtn = document.createElement('button');
        ctxAllBtn.className = 'val-action-btn val-action-btn-muted';
        ctxAllBtn.textContent = _ctxDefaultShown ? 'Hide All Context' : 'Show All Context';
        ctxAllRow.appendChild(ctxAllBtn);
        details.appendChild(ctxAllRow);

        function _updateCtxAllBtn() {
            const anyShown = [...cardsDiv.querySelectorAll('.val-ctx-toggle-btn')].some(b => b._isContextShown && b._isContextShown());
            ctxAllBtn.textContent = anyShown ? 'Hide All Context' : 'Show All Context';
        }
        ctxAllBtn.addEventListener('click', () => {
            const allBtns = [...cardsDiv.querySelectorAll('.val-ctx-toggle-btn')];
            const anyShown = allBtns.some(b => b._isContextShown && b._isContextShown());
            allBtns.forEach(b => {
                if (anyShown && b._isContextShown && b._isContextShown()) b.click();
                else if (!anyShown && b._showContext && !b._isContextShown()) b.click();
            });
            _updateCtxAllBtn();
        });

        details.appendChild(cardsDiv);

        if (isLowConf && sliderRow) {
            const sliderEl = sliderRow.querySelector('.lc-slider');
            const sliderValEl = sliderRow.querySelector('.lc-slider-val');
            const countEl = summary.querySelector('[data-lc-count]');
            sliderEl.addEventListener('input', () => {
                lcThreshold = parseInt(sliderEl.value);
                sliderValEl.textContent = `${lcThreshold}%`;
                const visible = getVisibleItems();
                if (countEl) countEl.textContent = visible.length;
                rebuildButtons(visible);
                if (state._cardRenderRafId) { cancelAnimationFrame(state._cardRenderRafId); state._cardRenderRafId = null; }
                cardsDiv.innerHTML = '';
                renderCategoryCards(cat.type, visible, cardsDiv);
            });
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

export async function refreshValidation() {
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;
    try {
        const globalState = captureValPanelState(dom.segValidationGlobalEl);
        const chState = captureValPanelState(dom.segValidationEl);
        const valResp = await fetch(`/api/seg/validate/${reciter}`);
        state.segValidation = await valResp.json();
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
        if (state.segData && state.segData.segments) {
            applyFiltersAndRender();
        } else if (state.segDisplayedSegments) {
            renderSegList(state.segDisplayedSegments);
        }
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

export function invalidateLoadedErrorCards() {
    document.querySelectorAll('details[data-category]').forEach(details => {
        if (details.open) details.open = false;
    });
}

export function refreshOpenAccordionCards() {
    document.querySelectorAll('details[data-category]').forEach(details => {
        if (!details.open) return;
        const cardsDiv = details.querySelector('.val-cards-container');
        if (!cardsDiv || !details._valCatItems) return;
        renderCategoryCards(details._valCatType, details._valCatItems, cardsDiv);
    });
}

// ---------------------------------------------------------------------------
// Validation index fixup helpers
// ---------------------------------------------------------------------------

function _forEachValItem(chapter, fn) {
    if (!state.segValidation) return;
    for (const cat of state._VAL_SINGLE_INDEX_CATS) {
        const arr = state.segValidation[cat];
        if (!arr) continue;
        for (const item of arr) {
            if (item.chapter === chapter) fn(item, 'seg_index');
        }
    }
    const mw = state.segValidation.missing_words;
    if (mw) {
        for (const item of mw) {
            if (item.chapter !== chapter) continue;
            if (item.seg_indices) {
                for (let i = 0; i < item.seg_indices.length; i++) {
                    const wrapped = { seg_index: item.seg_indices[i] };
                    fn(wrapped, 'seg_index');
                    item.seg_indices[i] = wrapped.seg_index;
                }
            }
            if (item.auto_fix) fn(item.auto_fix, 'target_seg_index');
        }
    }
}

export function _fixupValIndicesForSplit(chapter, splitIndex) {
    _forEachValItem(chapter, (item, key) => {
        if (item[key] > splitIndex) item[key] += 1;
    });
}

export function _fixupValIndicesForMerge(chapter, keptIndex, consumedIndex) {
    const maxIdx = Math.max(keptIndex, consumedIndex);
    _forEachValItem(chapter, (item, key) => {
        if (item[key] === consumedIndex) item[key] = keptIndex;
        else if (item[key] > maxIdx) item[key] -= 1;
    });
}

export function _fixupValIndicesForDelete(chapter, deletedIndex) {
    _forEachValItem(chapter, (item, key) => {
        if (item[key] === deletedIndex) item[key] = -1;
        else if (item[key] > deletedIndex) item[key] -= 1;
    });
}
