/**
 * Filter bar UI and filter application logic.
 */

import type { Segment } from '../types/domain';
import { SEG_FILTER_FIELDS, SEG_FILTER_OPS } from './constants';
import { countSegWords,parseSegRef } from './references';
import { renderSegList } from './rendering';
import { dom,state } from './state';

// ---------------------------------------------------------------------------
// Derived-property helpers for filtering
// ---------------------------------------------------------------------------

/** Derived per-segment numeric properties exposed to the filter predicate. */
export interface SegDerivedProps {
    duration_s: number;
    num_words: number;
    num_verses: number;
    confidence_pct: number;
    /** `null` when no "next" segment in the same entry — meaning "unknown". */
    silence_after_ms: number | null | undefined;
    [k: string]: number | null | undefined;
}

/** `Segment` with the cached derived-props field used by the filter. */
interface SegWithDerived extends Segment {
    _derived?: SegDerivedProps;
}

export function segDerivedProps(seg: SegWithDerived): SegDerivedProps {
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

export function computeSilenceAfter(): void {
    if (!state.segAllData) return;
    const pad = state.segAllData.pad_ms || 0;
    const segs = state.segAllData.segments;
    for (let i = 0; i < segs.length; i++) {
        const cur = segs[i];
        if (!cur) continue;
        const next = segs[i + 1];
        const sameEntry = next && cur.audio_url === next.audio_url
                               && cur.entry_idx === next.entry_idx;
        if (sameEntry && next) {
            cur.silence_after_ms = (next.time_start - cur.time_end) + 2 * pad;
            cur.silence_after_raw_ms = next.time_start - cur.time_end;
        } else {
            cur.silence_after_ms = null;
            cur.silence_after_raw_ms = null;
        }
    }
}

function _compareFilter(actual: number | null | undefined, op: string, value: number): boolean {
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

export function applyFiltersAndRender(): void {
    if (!state.segAllData) return;
    const chapter = dom.segChapterSelect.value;

    const activeValid = state.segActiveFilters.filter((f) => f.value !== null) as Array<
        { field: string; op: string; value: number }
    >;

    if (!chapter && activeValid.length === 0) {
        state.segDisplayedSegments = [];
        dom.segListEl.innerHTML = '<div class="seg-loading">Select a chapter or add a filter to view segments</div>';
        if (dom.segFilterStatusEl) dom.segFilterStatusEl.textContent = '';
        return;
    }

    let segs: Segment[] = state.segAllData.segments;

    if (chapter) {
        segs = segs.filter((s) => s.chapter === parseInt(chapter));
    }

    const verse = dom.segVerseSelect.value;
    if (verse && chapter) {
        const prefix = `${chapter}:${verse}:`;
        segs = segs.filter((s) => s.matched_ref && s.matched_ref.startsWith(prefix));
    }

    // Clear stale neighbour tags
    state.segAllData.segments.forEach((s) => { delete s._isNeighbour; });

    if (activeValid.length > 0) {
        const matched = segs.filter((seg) =>
            activeValid.every((f) => {
                const actual = segDerivedProps(seg as SegWithDerived)[f.field];
                return _compareFilter(actual, f.op, f.value);
            })
        );

        const hasNeighbourFilter = activeValid.some((f) =>
            SEG_FILTER_FIELDS.find((fd) => fd.value === f.field)?.neighbour
        );

        if (hasNeighbourFilter) {
            const posMap = new Map<Segment, number>(segs.map((s, i) => [s, i]));
            const resultSet = new Set<Segment>(matched);
            matched.forEach((seg) => {
                const idx = posMap.get(seg);
                if (idx === undefined) return;
                const next = segs[idx + 1];
                if (next && next.audio_url === seg.audio_url) {
                    next._isNeighbour = true;
                    resultSet.add(next);
                }
            });
            segs = segs.filter((seg) => resultSet.has(seg));

            const groups: Segment[][] = [];
            for (let i = 0; i < segs.length; i++) {
                const seg = segs[i];
                if (!seg) continue;
                if (!seg._isNeighbour) {
                    const group: Segment[] = [seg];
                    const nxt = segs[i + 1];
                    if (nxt && nxt._isNeighbour) {
                        group.push(nxt);
                        i++;
                    }
                    groups.push(group);
                }
            }
            groups.sort((a, b) => ((a[0]?.silence_after_ms ?? Infinity) - (b[0]?.silence_after_ms ?? Infinity)));
            segs = groups.flat();
        } else {
            segs = matched;
        }
    }

    const total = chapter
        ? state.segAllData.segments.filter((s) => s.chapter === parseInt(chapter)).length
        : state.segAllData.segments.length;
    if (dom.segFilterStatusEl) {
        dom.segFilterStatusEl.textContent = (activeValid.length > 0 || verse)
            ? `${segs.length} / ${total}` : '';
    }

    state.segDisplayedSegments = segs;
    state._segIndexMap = new Map(segs.map((s) => [`${s.chapter}:${s.index}`, s]));

    if (activeValid.length > 0 && state._segSavedFilterView) {
        state._segSavedFilterView = null;
    }

    renderSegList(state.segDisplayedSegments);
}

export function applyVerseFilterAndRender(): void {
    applyFiltersAndRender();
}

// ---------------------------------------------------------------------------
// Filter bar UI
// ---------------------------------------------------------------------------

export function renderFilterBar(): void {
    dom.segFilterRowsEl.innerHTML = '';
    state.segActiveFilters.forEach((f, i) => {
        const row = document.createElement('div');
        row.className = 'seg-filter-row';

        const fieldSel = document.createElement('select');
        fieldSel.className = 'seg-filter-field';
        SEG_FILTER_FIELDS.forEach((opt) => {
            const o = document.createElement('option');
            o.value = opt.value; o.textContent = opt.label; o.selected = opt.value === f.field;
            fieldSel.appendChild(o);
        });
        fieldSel.addEventListener('change', () => {
            const row = state.segActiveFilters[i];
            if (!row) return;
            row.field = fieldSel.value; applyFiltersAndRender();
        });

        const opSel = document.createElement('select');
        opSel.className = 'seg-filter-op';
        SEG_FILTER_OPS.forEach((op) => {
            const o = document.createElement('option');
            o.value = op; o.textContent = op; o.selected = op === f.op;
            opSel.appendChild(o);
        });
        opSel.addEventListener('change', () => {
            const row = state.segActiveFilters[i];
            if (!row) return;
            row.op = opSel.value; applyFiltersAndRender();
        });

        const valInput = document.createElement('input');
        valInput.type = 'number'; valInput.className = 'seg-filter-value';
        valInput.value = f.value != null ? String(f.value) : '';
        valInput.step = 'any'; valInput.placeholder = 'value';
        valInput.addEventListener('input', () => {
            const row = state.segActiveFilters[i];
            if (!row) return;
            const v = parseFloat(valInput.value);
            row.value = isNaN(v) ? null : v;
            if (state._segFilterDebounceTimer !== null) {
                clearTimeout(state._segFilterDebounceTimer);
            }
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

export function updateFilterBarControls(): void {
    const n = state.segActiveFilters.length;
    if (dom.segFilterCountEl) dom.segFilterCountEl.textContent = n > 0 ? `(${n})` : '';
    if (dom.segFilterClearBtn) dom.segFilterClearBtn.hidden = n === 0;
}

export function addSegFilterCondition(): void {
    state.segActiveFilters.push({ field: 'duration_s', op: '>', value: null });
    renderFilterBar(); updateFilterBarControls();
    dom.segFilterRowsEl.querySelectorAll<HTMLInputElement>('.seg-filter-value').forEach((el, i, arr) => {
        if (i === arr.length - 1) el.focus();
    });
}

export function clearAllSegFilters(): void {
    state.segActiveFilters = [];
    state._segSavedFilterView = null;
    renderFilterBar(); updateFilterBarControls(); applyFiltersAndRender();
}
