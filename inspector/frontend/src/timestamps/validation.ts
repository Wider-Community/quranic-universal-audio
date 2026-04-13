/**
 * Timestamps tab — validation panel rendering.
 */

import type { TsValidateResponse } from '../types/api';
import type { TsBoundaryMismatch,TsMfaFailure, TsMissingWords } from '../types/domain';
import { jumpToTsVerse } from './index';
import { dom } from './state';

// NOTE: circular dependency with index.ts (jumpToTsVerse).
// Safe because this function is only called at runtime, long after both
// modules have finished executing their top-level code.

interface TsValCategory<T> {
    name: string;
    items: T[];
    countClass: string;
    btnClass: string;
    getLabel: (i: T) => string;
    getTitle: (i: T) => string;
    getVerseKey: (i: T) => string;
}

/**
 * Render the timestamps validation panel (failed alignments, missing words,
 * boundary mismatches) from server-returned data.
 */
export function renderTsValidationPanel(data: TsValidateResponse | null): void {
    dom.tsValidationEl.innerHTML = '';
    if (!data) { dom.tsValidationEl.hidden = true; return; }

    const { mfa_failures, missing_words, boundary_mismatches } = data;
    const hasAny = [mfa_failures, missing_words, boundary_mismatches].some(a => a && a.length > 0);
    if (!hasAny) { dom.tsValidationEl.hidden = true; return; }
    dom.tsValidationEl.hidden = false;

    const mfaCat: TsValCategory<TsMfaFailure> = {
        name: 'Failed Alignments', items: mfa_failures || [],
        countClass: 'has-errors', btnClass: 'val-error',
        getLabel: i => i.label,
        getTitle: i => i.error || '',
        getVerseKey: i => i.verse_key,
    };
    const mwCat: TsValCategory<TsMissingWords> = {
        name: 'Missing Words', items: missing_words || [],
        countClass: 'has-errors', btnClass: 'val-error',
        getLabel: i => i.label,
        getTitle: i => `missing indices: ${(i.missing || []).join(', ')}`,
        getVerseKey: i => i.verse_key,
    };
    const bmCat: TsValCategory<TsBoundaryMismatch> = {
        name: 'Boundary Mismatches', items: boundary_mismatches || [],
        countClass: 'has-warnings', btnClass: 'val-warning',
        getLabel: i => i.label,
        // B17 fix: server emits `{side, diff_ms}`; the pre-refactor tooltip
        // read `{ts_ms, seg_ms}` (never emitted) and rendered "undefined ms
        // vs undefined ms". Use the actual fields.
        getTitle: i => `${i.side} boundary drift: ${i.diff_ms}ms`,
        getVerseKey: i => i.verse_key,
    };

    const renderCat = <T>(cat: TsValCategory<T>): void => {
        if (!cat.items.length) return;
        const details = document.createElement('details');
        const summary = document.createElement('summary');
        const badge = document.createElement('span');
        badge.className = `val-count ${cat.countClass}`;
        badge.textContent = String(cat.items.length);
        summary.textContent = cat.name + ' ';
        summary.appendChild(badge);
        details.appendChild(summary);

        const itemsDiv = document.createElement('div');
        itemsDiv.className = 'val-items';
        cat.items.forEach(issue => {
            const btn = document.createElement('button');
            btn.className = `val-btn ${cat.btnClass}`;
            btn.textContent = cat.getLabel(issue);
            btn.title = cat.getTitle(issue);
            btn.addEventListener('click', () => jumpToTsVerse(cat.getVerseKey(issue)));
            itemsDiv.appendChild(btn);
        });
        details.appendChild(itemsDiv);
        dom.tsValidationEl.appendChild(details);
    };

    renderCat(mfaCat);
    renderCat(mwCat);
    renderCat(bmCat);
}
