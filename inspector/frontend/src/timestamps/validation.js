/**
 * Timestamps tab — validation panel rendering.
 */

import { state, dom } from './state.js';
import { jumpToTsVerse } from './index.js';

// NOTE: circular dependency with index.js (jumpToTsVerse).
// Safe because this function is only called at runtime, long after both
// modules have finished executing their top-level code.

/**
 * Render the timestamps validation panel (failed alignments, missing words,
 * boundary mismatches) from server-returned data.
 */
export function renderTsValidationPanel(data) {
    dom.tsValidationEl.innerHTML = '';
    if (!data) { dom.tsValidationEl.hidden = true; return; }

    const { mfa_failures, missing_words, boundary_mismatches } = data;
    const hasAny = [mfa_failures, missing_words, boundary_mismatches].some(a => a && a.length > 0);
    if (!hasAny) { dom.tsValidationEl.hidden = true; return; }
    dom.tsValidationEl.hidden = false;

    const categories = [
        {
            name: 'Failed Alignments', items: mfa_failures || [],
            countClass: 'has-errors', btnClass: 'val-error',
            getLabel: i => i.label,
            getTitle: i => i.error || '',
        },
        {
            name: 'Missing Words', items: missing_words || [],
            countClass: 'has-errors', btnClass: 'val-error',
            getLabel: i => i.label,
            getTitle: i => `missing indices: ${(i.missing || []).join(', ')}`,
        },
        {
            name: 'Boundary Mismatches', items: boundary_mismatches || [],
            countClass: 'has-warnings', btnClass: 'val-warning',
            getLabel: i => i.label,
            getTitle: i => `timestamps ${i.ts_ms}ms vs segments ${i.seg_ms}ms`,
        },
    ];

    categories.forEach(cat => {
        if (!cat.items.length) return;
        const details = document.createElement('details');
        const summary = document.createElement('summary');
        const badge = document.createElement('span');
        badge.className = `val-count ${cat.countClass}`;
        badge.textContent = cat.items.length;
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
            btn.addEventListener('click', () => jumpToTsVerse(issue.verse_key));
            itemsDiv.appendChild(btn);
        });
        details.appendChild(itemsDiv);
        dom.tsValidationEl.appendChild(details);
    });
}
