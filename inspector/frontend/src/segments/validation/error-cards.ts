/**
 * Error card rendering for validation accordions.
 * Renders segment cards inside accordion panels with context, auto-fix, ignore.
 *
 * Wave 8a.2: renderCategoryCards / resolveIssueToSegment / addContextToggle removed
 * (ValidationPanel.svelte + ErrorCard.svelte own the imperative rendering now).
 * _rebuildAccordionAfterSplit/_rebuildAccordionAfterMerge remain (called from edit/).
 */

import type { Segment } from '../../types/domain';
import { getAdjacentSegments } from '../data';
import { renderSegCard, resolveSegFromRow } from '../rendering';
import { state } from '../state';
import { _ensureWaveformObserver } from '../waveform/index';

// ---------------------------------------------------------------------------
// Local interface types
// ---------------------------------------------------------------------------

interface ErrorCardOptions {
    isContext?: boolean;
    contextLabel?: string;
    readOnly?: boolean;
}

// ---------------------------------------------------------------------------
// renderErrorCard -- wrapper around renderSegCard with error-card defaults
// ---------------------------------------------------------------------------

function renderErrorCard(seg: Segment, options: ErrorCardOptions = {}): HTMLElement {
    const { isContext = false, contextLabel = '', readOnly = false } = options;
    return renderSegCard(seg, {
        showChapter: true,
        showPlayBtn: true,
        showGotoBtn: !isContext && !readOnly,
        isContext,
        contextLabel,
        readOnly,
    });
}

export function ensureContextShown(row: Element): void {
    const wrapper = row.closest('.val-card-wrapper');
    if (!wrapper) return;
    const btn = wrapper.querySelector<HTMLButtonElement>('.val-ctx-toggle-btn');
    if (btn && btn.textContent?.trim() === 'Show Context') btn.click();
}

export function _isWrapperContextShown(wrapper: Element | null | undefined): boolean {
    if (!wrapper) return false;
    const btn = wrapper.querySelector<HTMLButtonElement>('.val-ctx-toggle-btn');
    return btn?.textContent?.trim() === 'Hide Context';
}

// ---------------------------------------------------------------------------
// _rebuildAccordionAfterSplit
// ---------------------------------------------------------------------------

function _buildSegUidMap(segs: Segment[]): Map<string, Segment> {
    const map = new Map<string, Segment>();
    for (const s of segs) {
        if (s.segment_uid) map.set(s.segment_uid, s);
    }
    return map;
}

export function _rebuildAccordionAfterSplit(
    wrapper: HTMLElement,
    chapter: number,
    origSeg: Segment,
    firstHalf: Segment,
    secondHalf: Segment,
): void {
    const observer = _ensureWaveformObserver();
    const allSegs: Segment[] = state.segAllData?.segments || state.segData?.segments || [];
    const uidMap = _buildSegUidMap(allSegs);
    wrapper.querySelectorAll('.seg-row-context').forEach((c) => c.remove());
    const mainCards = [...wrapper.querySelectorAll<HTMLElement>('.seg-row:not(.seg-row-context)')];
    const splitCard = mainCards.find((c) =>
        (origSeg.segment_uid && c.dataset.segUid === origSeg.segment_uid) ||
        (parseInt(c.dataset.segChapter ?? '') === (origSeg.chapter ?? chapter) &&
            parseInt(c.dataset.segIndex ?? '') === origSeg.index));
    if (splitCard) {
        const f = renderErrorCard(firstHalf);
        const s = renderErrorCard(secondHalf);
        wrapper.insertBefore(f, splitCard);
        wrapper.insertBefore(s, splitCard);
        splitCard.remove();
        [f, s].forEach((c) => c.querySelectorAll<HTMLCanvasElement>('canvas[data-needs-waveform]').forEach((cv) => observer.observe(cv)));
    } else {
        const actionsRow = wrapper.querySelector('.val-card-actions');
        [renderErrorCard(firstHalf), renderErrorCard(secondHalf)].forEach((c) => {
            if (actionsRow) wrapper.insertBefore(c, actionsRow);
            else wrapper.appendChild(c);
            c.querySelectorAll<HTMLCanvasElement>('canvas[data-needs-waveform]').forEach((cv) => observer.observe(cv));
        });
    }
    wrapper.querySelectorAll<HTMLElement>('.seg-row:not(.seg-row-context)').forEach((card) => {
        const uid = card.dataset.segUid;
        if (!uid) return;
        const updatedSeg = uidMap.get(uid);
        if (updatedSeg) card.dataset.segIndex = String(updatedSeg.index);
    });
    const updatedMain = [...wrapper.querySelectorAll<HTMLElement>('.seg-row:not(.seg-row-context)')];
    if (updatedMain.length === 0) return;
    const firstMainSeg = resolveSegFromRow(updatedMain[0]);
    const lastMainSeg  = resolveSegFromRow(updatedMain[updatedMain.length - 1]);
    if (firstMainSeg) {
        const { prev } = getAdjacentSegments(firstMainSeg.chapter ?? chapter, firstMainSeg.index);
        if (prev) {
            const prevCard = renderErrorCard(prev, { isContext: true, contextLabel: 'Previous' });
            wrapper.insertBefore(prevCard, updatedMain[0] ?? null);
            prevCard.querySelectorAll<HTMLCanvasElement>('canvas[data-needs-waveform]').forEach((c) => observer.observe(c));
        }
    }
    if (lastMainSeg) {
        const { next } = getAdjacentSegments(lastMainSeg.chapter ?? chapter, lastMainSeg.index);
        if (next) {
            const actionsRow = wrapper.querySelector('.val-card-actions');
            const nextCard = renderErrorCard(next, { isContext: true, contextLabel: 'Next' });
            if (actionsRow) wrapper.insertBefore(nextCard, actionsRow);
            else wrapper.appendChild(nextCard);
            nextCard.querySelectorAll<HTMLCanvasElement>('canvas[data-needs-waveform]').forEach((c) => observer.observe(c));
        }
    }
}

// ---------------------------------------------------------------------------
// _refreshSiblingCardIndices -- no-op (indices refreshed in rebuild)
// ---------------------------------------------------------------------------

export function _refreshSiblingCardIndices(): void {
    // Indices are refreshed during _rebuildAccordionAfterSplit
}

/** Refresh `data-seg-index` on every open-accordion card by UID, so stale
 *  indices after split/merge/delete don't misroute playback via
 *  resolveSegFromRow → _segIndexMap. `skipWrapper` excludes a wrapper that
 *  was just rebuilt in-place. */
export function _refreshStaleSegIndices(skipWrapper?: HTMLElement): void {
    const allSegs: Segment[] = state.segAllData?.segments || state.segData?.segments || [];
    if (!allSegs.length) return;
    const uidMap = _buildSegUidMap(allSegs);
    document.querySelectorAll<HTMLElement>('details[data-category] .seg-row[data-seg-uid]').forEach((card) => {
        if (skipWrapper && skipWrapper.contains(card)) return;
        const uid = card.dataset.segUid;
        if (!uid) return;
        const seg = uidMap.get(uid);
        if (seg) card.dataset.segIndex = String(seg.index);
    });
}

// ---------------------------------------------------------------------------
// _rebuildAccordionAfterMerge
// ---------------------------------------------------------------------------

export function _rebuildAccordionAfterMerge(
    wrapper: HTMLElement,
    chapter: number,
    merged: Segment,
    direction: 'prev' | 'next' | undefined,
): void {
    const { prev, next } = getAdjacentSegments(merged.chapter ?? chapter, merged.index);
    const issueLabel = wrapper.querySelector('.val-card-issue-label');
    wrapper.innerHTML = '';
    if (issueLabel) wrapper.appendChild(issueLabel);
    if (direction === 'prev' && next) {
        wrapper.appendChild(renderErrorCard(merged));
        wrapper.appendChild(renderErrorCard(next, { isContext: true, contextLabel: 'Next' }));
    } else if (direction === 'next' && prev) {
        wrapper.appendChild(renderErrorCard(prev, { isContext: true, contextLabel: 'Previous' }));
        wrapper.appendChild(renderErrorCard(merged));
    } else {
        wrapper.appendChild(renderErrorCard(merged));
    }
    const observer = _ensureWaveformObserver();
    wrapper.querySelectorAll<HTMLCanvasElement>('canvas[data-needs-waveform]').forEach((c) => observer.observe(c));
}
