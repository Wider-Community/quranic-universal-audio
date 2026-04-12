/**
 * Error card rendering for validation accordions.
 * Renders segment cards inside accordion panels with context, auto-fix, ignore.
 */

import { state, dom, createOp, snapshotSeg, finalizeOp, markDirty, unmarkDirty, isDirty, isIndexDirty } from '../state';
import { _isIgnoredFor } from './categories';
import { getChapterSegments, getSegByChapterIndex, getAdjacentSegments } from '../data';
import { renderSegCard, syncAllCardsForSegment, resolveSegFromRow } from '../rendering';
import { commitRefEdit } from '../edit/reference';
import { _ensureWaveformObserver, _fetchPeaks } from '../waveform/index';
import { findMissingVerseBoundarySegments } from '../navigation';
import type { Segment, SegValAnyItem, SegValMissingWordsItem, SegValMissingVerseItem } from '../../types/domain';

// ---------------------------------------------------------------------------
// Local interface types
// ---------------------------------------------------------------------------

interface ErrorCardOptions {
    isContext?: boolean;
    contextLabel?: string;
    readOnly?: boolean;
}

interface ContextToggleOptions {
    defaultOpen?: boolean;
    nextOnly?: boolean;
}

/** Button augmented by `addContextToggle` with instance callbacks. */
interface CtxToggleButton extends HTMLButtonElement {
    _showContext?: () => void;
    _isContextShown?: () => boolean;
}

/** Seg + its currently-rendered card, tracked inside a wrapper. */
interface SegInWrapper {
    seg: Segment;
    card: HTMLElement;
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

// ---------------------------------------------------------------------------
// renderCategoryCards -- render all items for a validation category
// ---------------------------------------------------------------------------

export function renderCategoryCards(type: string, items: SegValAnyItem[], container: HTMLElement): void {
    if (state._cardRenderRafId) { cancelAnimationFrame(state._cardRenderRafId); state._cardRenderRafId = null; }
    container.innerHTML = '';
    if (!state.segAllData || !items || items.length === 0) return;

    const BATCH_SIZE = 30;
    const observer = _ensureWaveformObserver();

    if (state.segPeaksByAudio) {
        const missingChapters = new Set<number>();
        items.forEach((item) => {
            const ch = item.chapter;
            if (!ch) return;
            const url = state.segAllData?.audio_by_chapter?.[String(ch)] || '';
            if (url && state.segPeaksByAudio && !state.segPeaksByAudio[url]) missingChapters.add(ch);
        });
        if (missingChapters.size > 0) {
            const reciter = dom.segReciterSelect.value;
            if (reciter) _fetchPeaks(reciter, [...missingChapters]);
        }
    }

    function renderOneItem(issue: SegValAnyItem): void {
        if (type === 'missing_words') {
            const mwIssue = issue as SegValMissingWordsItem;
            const wrapper = document.createElement('div');
            wrapper.className = 'val-card-wrapper';
            const gapLabel = document.createElement('div');
            gapLabel.className = 'val-card-gap-label';
            gapLabel.textContent = mwIssue.msg || 'Missing words between segments';
            wrapper.appendChild(gapLabel);
            const indices = mwIssue.seg_indices || [];
            const segsInWrapper: SegInWrapper[] = [];
            indices.forEach((idx) => {
                const seg = getSegByChapterIndex(mwIssue.chapter, idx);
                if (seg) {
                    const card = renderErrorCard(seg);
                    wrapper.appendChild(card);
                    segsInWrapper.push({ seg, card });
                }
            });
            const actionsRow = document.createElement('div');
            actionsRow.className = 'val-card-actions';
            if (mwIssue.auto_fix) {
                const autoFix = mwIssue.auto_fix;
                const fixBtn = document.createElement('button');
                fixBtn.className = 'val-action-btn';
                fixBtn.textContent = 'Auto Fix';
                fixBtn.title = 'Extend segment ref to cover the missing word';
                fixBtn.addEventListener('click', async () => {
                    const seg = getSegByChapterIndex(mwIssue.chapter, autoFix.target_seg_index);
                    if (!seg) return;
                    const oldRef = seg.matched_ref || '';
                    const oldText = seg.matched_text || '';
                    const oldDisplay = seg.display_text || '';
                    const oldConf = seg.confidence;
                    const oldIgnoredCats = seg.ignored_categories ? [...seg.ignored_categories] : null;
                    const segChapter = seg.chapter ?? mwIssue.chapter;
                    const wasDirty = isIndexDirty(segChapter, seg.index);
                    state._pendingOp = createOp('auto_fix_missing_word', { contextCategory: 'missing_words', fixKind: 'auto_fix' });
                    state._pendingOp.targets_before = [snapshotSeg(seg)];
                    const _autoFixOpId = state._pendingOp.op_id;
                    const newRef = `${autoFix.new_ref_start}-${autoFix.new_ref_end}`;
                    const entry = segsInWrapper.find((s) => s.seg === seg);
                    const card = entry?.card || wrapper;
                    await commitRefEdit(seg, newRef, card);
                    wrapper.style.opacity = '0.5';
                    fixBtn.disabled = true;
                    fixBtn.textContent = 'Fixed (save to apply)';
                    const undoBtn = document.createElement('button');
                    undoBtn.className = 'val-action-btn val-action-btn-danger';
                    undoBtn.textContent = 'Undo';
                    undoBtn.title = 'Revert auto-fix';
                    undoBtn.addEventListener('click', () => {
                        seg.matched_ref = oldRef;
                        seg.matched_text = oldText;
                        seg.display_text = oldDisplay;
                        seg.confidence = oldConf;
                        if (oldIgnoredCats) seg.ignored_categories = oldIgnoredCats; else delete seg.ignored_categories;
                        if (!wasDirty) unmarkDirty(segChapter, seg.index);
                        fixBtn.disabled = false;
                        fixBtn.textContent = 'Auto Fix';
                        wrapper.style.opacity = '1';
                        syncAllCardsForSegment(seg);
                        undoBtn.remove();
                        dom.segSaveBtn.disabled = !isDirty();
                        const ops = state.segOpLog.get(segChapter);
                        if (ops) { const idx = ops.findIndex((o) => o.op_id === _autoFixOpId); if (idx !== -1) ops.splice(idx, 1); }
                    });
                    fixBtn.after(undoBtn);
                });
                actionsRow.appendChild(fixBtn);
            }
            if (segsInWrapper.length > 0) addContextToggle(actionsRow, segsInWrapper);
            wrapper.appendChild(actionsRow);
            container.appendChild(wrapper);
        } else if (type === 'missing_verses') {
            const mvIssue = issue as SegValMissingVerseItem;
            const wrapper = document.createElement('div');
            wrapper.className = 'val-card-wrapper';
            const msgLabel = document.createElement('div');
            msgLabel.className = 'val-card-issue-label';
            msgLabel.textContent = mvIssue.msg ? `${mvIssue.verse_key} \u2014 ${mvIssue.msg}` : mvIssue.verse_key;
            wrapper.appendChild(msgLabel);
            const { prev, next } = findMissingVerseBoundarySegments(mvIssue.chapter, mvIssue.verse_key);
            const segsInWrapper: SegInWrapper[] = [];
            if (prev) { const prevCard = renderErrorCard(prev, { contextLabel: 'Previous verse boundary', readOnly: true }); wrapper.appendChild(prevCard); segsInWrapper.push({ seg: prev, card: prevCard }); }
            if (next && (!prev || next.index !== prev.index)) { const nextCard = renderErrorCard(next, { contextLabel: 'Next verse boundary', readOnly: true }); wrapper.appendChild(nextCard); segsInWrapper.push({ seg: next, card: nextCard }); }
            if (segsInWrapper.length === 0) { const empty = document.createElement('div'); empty.className = 'seg-loading'; empty.textContent = 'No boundary segments found for this missing verse.'; wrapper.appendChild(empty); }
            else { const actionsRow = document.createElement('div'); actionsRow.className = 'val-card-actions'; addContextToggle(actionsRow, segsInWrapper); wrapper.appendChild(actionsRow); }
            container.appendChild(wrapper);
        } else {
            const seg = resolveIssueToSegment(type, issue);
            if (!seg) return;
            const wrapper = document.createElement('div');
            wrapper.className = 'val-card-wrapper';
            const issueMsg: string | undefined = (issue as { msg?: string }).msg;
            const issueGt: string | undefined = (issue as { gt_tail?: string }).gt_tail;
            const issueAsr: string | undefined = (issue as { asr_tail?: string }).asr_tail;
            if (issueMsg) {
                const msgLabel = document.createElement('div');
                msgLabel.className = 'val-card-issue-label';
                msgLabel.textContent = issueMsg;
                wrapper.appendChild(msgLabel);
            }
            const card = renderErrorCard(seg);
            wrapper.appendChild(card);
            if (type === 'boundary_adj' && state.SHOW_BOUNDARY_PHONEMES && (issueGt || issueAsr)) {
                const textBox = card.querySelector('.seg-text');
                if (textBox) {
                    const tailEl = document.createElement('div');
                    tailEl.className = 'val-phoneme-tail';
                    const gt = issueGt || '';
                    const asr = issueAsr || '';
                    tailEl.innerHTML = `<span class="val-tail-label">GT:</span> <span class="val-tail-phonemes">${gt}</span>\n<span class="val-tail-label">ASR:</span> <span class="val-tail-phonemes">${asr}</span>`;
                    textBox.appendChild(tailEl);
                }
            }
            const actionsRow = document.createElement('div');
            actionsRow.className = 'val-card-actions';
            if ((type === 'boundary_adj' || type === 'cross_verse' || type === 'audio_bleeding' || type === 'repetitions' || type === 'qalqala') || (type === 'low_confidence' && seg.confidence < 1.0)) {
                const ignoreBtn = document.createElement('button');
                ignoreBtn.className = 'val-action-btn ignore-btn';
                const segChapterForBtn = seg.chapter ?? parseInt(dom.segChapterSelect.value);
                const isDirtySegment = state.segDirtyMap.get(segChapterForBtn)?.indices?.has(seg.index);
                if (_isIgnoredFor(seg, type)) { ignoreBtn.disabled = true; ignoreBtn.textContent = 'Ignored'; wrapper.style.opacity = '0.5'; }
                else if (isDirtySegment) { ignoreBtn.disabled = true; ignoreBtn.textContent = 'Ignore'; ignoreBtn.title = 'Cannot ignore \u2014 this segment already has unsaved edits'; }
                else { ignoreBtn.textContent = 'Ignore'; ignoreBtn.title = 'Dismiss this issue for this category'; }
                ignoreBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (_isIgnoredFor(seg, type)) return;
                    const segChapter = seg.chapter ?? parseInt(dom.segChapterSelect.value);
                    let ignoreOp;
                    try { ignoreOp = createOp('ignore_issue', { contextCategory: type, fixKind: 'ignore' }); ignoreOp.targets_before = [snapshotSeg(seg)]; ignoreOp.applied_at_utc = ignoreOp.started_at_utc; } catch (err) { console.warn('Ignore: edit history snapshot failed:', err); }
                    if (!seg.ignored_categories) seg.ignored_categories = [];
                    seg.ignored_categories.push(type);
                    // Clear the filter-cache on the segment so filters re-derive.
                    delete (seg as Segment & { _derived?: unknown })._derived;
                    markDirty(segChapter, seg.index);
                    syncAllCardsForSegment(seg);
                    if (ignoreOp) { try { ignoreOp.targets_after = [snapshotSeg(seg)]; finalizeOp(segChapter, ignoreOp); } catch (err) { console.warn('Ignore: edit history finalize failed:', err); } }
                    ignoreBtn.disabled = true; ignoreBtn.textContent = 'Ignored'; wrapper.style.opacity = '0.5';
                });
                actionsRow.appendChild(ignoreBtn);
            }
            wrapper.appendChild(actionsRow);
            const ctxMode = state._accordionContext?.[type] ?? 'hidden';
            const contextDefault = ctxMode !== 'hidden';
            const nextOnly = ctxMode === 'next_only';
            addContextToggle(actionsRow, [{ seg, card }], { defaultOpen: contextDefault, nextOnly });
            container.appendChild(wrapper);
        }
    }

    function processBatch(startIdx: number): void {
        const end = Math.min(startIdx + BATCH_SIZE, items.length);
        for (let i = startIdx; i < end; i++) {
            const item = items[i];
            if (item) renderOneItem(item);
        }
        container.querySelectorAll<HTMLCanvasElement>('canvas[data-needs-waveform]').forEach((c) => observer.observe(c));
        if (end < items.length) { state._cardRenderRafId = requestAnimationFrame(() => processBatch(end)); }
        else { state._cardRenderRafId = null; }
    }

    processBatch(0);
}

// ---------------------------------------------------------------------------
// resolveIssueToSegment -- find the segment for a validation issue
// ---------------------------------------------------------------------------

export function resolveIssueToSegment(type: string, issue: SegValAnyItem): Segment | null {
    const anyIssue = issue as { seg_index?: number; ref?: string; verse_key?: string; chapter: number };
    if (anyIssue.seg_index != null && anyIssue.seg_index < 0) return null;
    if (type === 'failed' || type === 'low_confidence' || type === 'boundary_adj' || type === 'cross_verse' || type === 'audio_bleeding' || type === 'repetitions' || type === 'muqattaat' || type === 'qalqala') {
        if (anyIssue.seg_index == null) return null;
        const seg = getSegByChapterIndex(anyIssue.chapter, anyIssue.seg_index);
        if (seg && anyIssue.ref && seg.matched_ref !== anyIssue.ref) {
            const byRef = getChapterSegments(anyIssue.chapter).find((s) => s.matched_ref === anyIssue.ref);
            if (byRef) return byRef;
        }
        return seg;
    }
    if (type === 'errors') {
        const vk = anyIssue.verse_key || '';
        const parts = vk.split(':');
        const prefix = parts.length >= 2 ? `${parts[0]}:${parts[1]}:` : vk;
        const chapterSegs = getChapterSegments(anyIssue.chapter);
        return chapterSegs.find((s) => s.matched_ref && s.matched_ref.startsWith(prefix)) || chapterSegs[0] || null;
    }
    return null;
}

// ---------------------------------------------------------------------------
// Context toggle (show/hide prev/next segments around an error card)
// ---------------------------------------------------------------------------

export function addContextToggle(
    actionsContainer: HTMLElement,
    segsInWrapper: SegInWrapper[],
    { defaultOpen = false, nextOnly = false }: ContextToggleOptions = {},
): void {
    const ctxBtn = document.createElement('button') as CtxToggleButton;
    ctxBtn.className = 'val-action-btn val-action-btn-muted val-ctx-toggle-btn';
    ctxBtn.textContent = 'Show Context';
    let contextShown = false;
    let contextEls: HTMLElement[] = [];

    function showContext(): void {
        const first = segsInWrapper[0];
        const last = segsInWrapper[segsInWrapper.length - 1];
        if (!first || !last) return;
        const cardParent = first.card.parentNode;
        if (!cardParent) return;
        const firstChapter = first.seg.chapter;
        const lastChapter = last.seg.chapter;
        if (firstChapter == null || lastChapter == null) return;
        const { prev } = getAdjacentSegments(firstChapter, first.seg.index);
        const { next } = getAdjacentSegments(lastChapter, last.seg.index);
        if (!nextOnly && prev) {
            const prevCard = renderErrorCard(prev, { isContext: true, contextLabel: 'Previous' });
            cardParent.insertBefore(prevCard, first.card);
            contextEls.push(prevCard);
        }
        if (next) {
            const nextCard = renderErrorCard(next, { isContext: true, contextLabel: 'Next' });
            if (last.card.nextSibling) {
                cardParent.insertBefore(nextCard, last.card.nextSibling);
            } else {
                cardParent.insertBefore(nextCard, actionsContainer);
            }
            contextEls.push(nextCard);
        }
        ctxBtn.textContent = 'Hide Context';
        contextShown = true;
    }

    function hideContext(): void {
        contextEls.forEach((el) => el.remove());
        contextEls = [];
        ctxBtn.textContent = 'Show Context';
        contextShown = false;
    }

    ctxBtn._showContext = showContext;
    ctxBtn._isContextShown = () => contextShown;
    ctxBtn.addEventListener('click', () => { if (contextShown) hideContext(); else showContext(); });
    actionsContainer.appendChild(ctxBtn);
    if (defaultOpen) showContext();
}

export function ensureContextShown(row: Element): void {
    const wrapper = row.closest('.val-card-wrapper');
    if (!wrapper) return;
    const actionsRow = wrapper.querySelector<HTMLElement>('.val-card-actions');
    if (!actionsRow) return;
    for (const child of Array.from(actionsRow.children)) {
        const btn = child as CtxToggleButton;
        if (typeof btn._showContext === 'function') {
            if (btn._isContextShown?.() !== true) btn._showContext();
            return;
        }
    }
}

export function _isWrapperContextShown(wrapper: Element | null | undefined): boolean {
    if (!wrapper) return false;
    const actionsRow = wrapper.querySelector<HTMLElement>('.val-card-actions');
    if (!actionsRow) return false;
    for (const child of Array.from(actionsRow.children)) {
        const btn = child as CtxToggleButton;
        if (typeof btn._isContextShown === 'function') return btn._isContextShown();
    }
    return false;
}

// ---------------------------------------------------------------------------
// _rebuildAccordionAfterSplit
// ---------------------------------------------------------------------------

export function _rebuildAccordionAfterSplit(
    wrapper: HTMLElement,
    chapter: number,
    origSeg: Segment,
    firstHalf: Segment,
    secondHalf: Segment,
): void {
    const observer = _ensureWaveformObserver();
    const allSegs: Segment[] = state.segAllData?.segments || state.segData?.segments || [];
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
        const updatedSeg = allSegs.find((s) => s.segment_uid === uid);
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
