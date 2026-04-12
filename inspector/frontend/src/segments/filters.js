/**
 * Filter bar UI and filter application logic.
 */

import { state, dom, SEG_FILTER_FIELDS, SEG_FILTER_OPS } from './state.js';
import { parseSegRef, countSegWords } from './references.js';
import { renderSegList } from './rendering.js';

// ---------------------------------------------------------------------------
// Derived-property helpers for filtering
// ---------------------------------------------------------------------------

export function segDerivedProps(seg) {
    if (seg._derived) return seg._derived;
    const duration_s     = (seg.time_end - seg.time_start) / 1000;
    const num_words      = countSegWords(seg.matched_ref);
    const p              = parseSegRef(seg.matched_ref);
    const num_verses     = p ? p.ayah_to - p.ayah_from + 1 : 0;
    const confidence_pct = (seg.confidence || 0) * 100;
    const silence_after_ms = seg.silence_after_ms;
    seg._derived = { duration_s, num_words, num_verses, confidence_pct, silence_after_ms };
    return seg._derived;
}

export function computeSilenceAfter() {
    if (!state.segAllData) return;
    const pad = state.segAllData.pad_ms || 0;
    const segs = state.segAllData.segments;
    for (let i = 0; i < segs.length; i++) {
        const next = segs[i + 1];
        const sameEntry = next && segs[i].audio_url === next.audio_url
                               && segs[i].entry_idx === next.entry_idx;
        if (sameEntry) {
            segs[i].silence_after_ms = (next.time_start - segs[i].time_end) + 2 * pad;
            segs[i].silence_after_raw_ms = next.time_start - segs[i].time_end;
        } else {
            segs[i].silence_after_ms = null;
            segs[i].silence_after_raw_ms = null;
        }
    }
}

function _compareFilter(actual, op, value) {
    if (actual == null) return false;
    switch (op) {
        case '>':  return actual >  value;
        case '>=': return actual >= value;
        case '<':  return actual <  value;
        case '<=': return actual <= value;
        case '=':  return actual === value;
        default:   return true;
    }
}

// ---------------------------------------------------------------------------
// Filter application
// ---------------------------------------------------------------------------

export function applyFiltersAndRender() {
    if (!state.segAllData) return;
    const chapter = dom.segChapterSelect.value;

    const activeValid = state.segActiveFilters.filter(f => f.value !== null);

    if (!chapter && activeValid.length === 0) {
        state.segDisplayedSegments = [];
        dom.segListEl.innerHTML = '<div class="seg-loading">Select a chapter or add a filter to view segments</div>';
        if (dom.segFilterStatusEl) dom.segFilterStatusEl.textContent = '';
        return;
    }

    let segs = state.segAllData.segments;

    if (chapter) {
        segs = segs.filter(s => s.chapter === parseInt(chapter));
    }

    const verse = dom.segVerseSelect.value;
    if (verse && chapter) {
        const prefix = `${chapter}:${verse}:`;
        segs = segs.filter(s => s.matched_ref && s.matched_ref.startsWith(prefix));
    }

    // Clear stale neighbour tags
    state.segAllData.segments.forEach(s => delete s._isNeighbour);

    if (activeValid.length > 0) {
        const matched = segs.filter(seg =>
            activeValid.every(f => {
                const actual = segDerivedProps(seg)[f.field];
                return _compareFilter(actual, f.op, f.value);
            })
        );

        const hasNeighbourFilter = activeValid.some(f =>
            SEG_FILTER_FIELDS.find(fd => fd.value === f.field)?.neighbour
        );

        if (hasNeighbourFilter) {
            const posMap = new Map(segs.map((s, i) => [s, i]));
            const resultSet = new Set(matched);
            matched.forEach(seg => {
                const idx = posMap.get(seg);
                const next = segs[idx + 1];
                if (next && next.audio_url === seg.audio_url) {
                    next._isNeighbour = true;
                    resultSet.add(next);
                }
            });
            segs = segs.filter(seg => resultSet.has(seg));

            const groups = [];
            for (let i = 0; i < segs.length; i++) {
                if (!segs[i]._isNeighbour) {
                    const group = [segs[i]];
                    if (segs[i + 1] && segs[i + 1]._isNeighbour) {
                        group.push(segs[++i]);
                    }
                    groups.push(group);
                }
            }
            groups.sort((a, b) => (a[0].silence_after_ms ?? Infinity) - (b[0].silence_after_ms ?? Infinity));
            segs = groups.flat();
        } else {
            segs = matched;
        }
    }

    const total = chapter
        ? state.segAllData.segments.filter(s => s.chapter === parseInt(chapter)).length
        : state.segAllData.segments.length;
    if (dom.segFilterStatusEl) {
        dom.segFilterStatusEl.textContent = (activeValid.length > 0 || verse)
            ? `${segs.length} / ${total}` : '';
    }

    state.segDisplayedSegments = segs;
    state._segIndexMap = new Map(segs.map(s => [`${s.chapter}:${s.index}`, s]));

    if (activeValid.length > 0 && state._segSavedFilterView) {
        state._segSavedFilterView = null;
    }

    renderSegList(state.segDisplayedSegments);
}

export function applyVerseFilterAndRender() {
    applyFiltersAndRender();
}

// ---------------------------------------------------------------------------
// Filter bar UI
// ---------------------------------------------------------------------------

export function renderFilterBar() {
    dom.segFilterRowsEl.innerHTML = '';
    state.segActiveFilters.forEach((f, i) => {
        const row = document.createElement('div');
        row.className = 'seg-filter-row';

        const fieldSel = document.createElement('select');
        fieldSel.className = 'seg-filter-field';
        SEG_FILTER_FIELDS.forEach(opt => {
            const o = document.createElement('option');
            o.value = opt.value; o.textContent = opt.label; o.selected = opt.value === f.field;
            fieldSel.appendChild(o);
        });
        fieldSel.addEventListener('change', () => {
            state.segActiveFilters[i].field = fieldSel.value; applyFiltersAndRender();
        });

        const opSel = document.createElement('select');
        opSel.className = 'seg-filter-op';
        SEG_FILTER_OPS.forEach(op => {
            const o = document.createElement('option');
            o.value = op; o.textContent = op; o.selected = op === f.op;
            opSel.appendChild(o);
        });
        opSel.addEventListener('change', () => {
            state.segActiveFilters[i].op = opSel.value; applyFiltersAndRender();
        });

        const valInput = document.createElement('input');
        valInput.type = 'number'; valInput.className = 'seg-filter-value';
        valInput.value = f.value ?? ''; valInput.step = 'any'; valInput.placeholder = 'value';
        valInput.addEventListener('input', () => {
            const v = parseFloat(valInput.value);
            state.segActiveFilters[i].value = isNaN(v) ? null : v;
            clearTimeout(state._segFilterDebounceTimer);
            state._segFilterDebounceTimer = setTimeout(applyFiltersAndRender, 300);
        });

        const removeBtn = document.createElement('button');
        removeBtn.className = 'btn btn-sm btn-cancel seg-filter-remove';
        removeBtn.textContent = '\u00d7';
        removeBtn.addEventListener('click', () => {
            state.segActiveFilters.splice(i, 1);
            renderFilterBar(); updateFilterBarControls(); applyFiltersAndRender();
        });

        row.append(fieldSel, opSel, valInput, removeBtn);
        dom.segFilterRowsEl.appendChild(row);
    });
}

export function updateFilterBarControls() {
    const n = state.segActiveFilters.length;
    if (dom.segFilterCountEl) dom.segFilterCountEl.textContent = n > 0 ? `(${n})` : '';
    if (dom.segFilterClearBtn) dom.segFilterClearBtn.hidden = n === 0;
}

export function addSegFilterCondition() {
    state.segActiveFilters.push({ field: 'duration_s', op: '>', value: null });
    renderFilterBar(); updateFilterBarControls();
    dom.segFilterRowsEl.querySelectorAll('.seg-filter-value').forEach((el, i, arr) => {
        if (i === arr.length - 1) el.focus();
    });
}

export function clearAllSegFilters() {
    state.segActiveFilters = [];
    state._segSavedFilterView = null;
    renderFilterBar(); updateFilterBarControls(); applyFiltersAndRender();
}
