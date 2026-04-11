/**
 * Error card rendering for validation accordions.
 * Renders segment cards inside accordion panels with context, auto-fix, ignore.
 */

import { state, dom, createOp, snapshotSeg, finalizeOp, markDirty, unmarkDirty, isDirty, isIndexDirty } from './state.js';
import { _isIgnoredFor } from './categories.js';
import { getChapterSegments, getSegByChapterIndex, getAdjacentSegments, syncChapterSegsToAll } from './data.js';
import { renderSegCard, syncAllCardsForSegment, resolveSegFromRow } from './rendering.js';
import { commitRefEdit } from './edit-reference.js';
import { _ensureWaveformObserver, _fetchPeaks } from './waveform.js';
import { findMissingVerseBoundarySegments, jumpToSegment, jumpToVerse, jumpToMissingVerseContext } from './navigation.js';

// ---------------------------------------------------------------------------
// renderErrorCard -- wrapper around renderSegCard with error-card defaults
// ---------------------------------------------------------------------------

function renderErrorCard(seg, options = {}) {
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

export function renderCategoryCards(type, items, container) {
    if (state._cardRenderRafId) { cancelAnimationFrame(state._cardRenderRafId); state._cardRenderRafId = null; }
    container.innerHTML = '';
    if (!state.segAllData || !items || items.length === 0) return;

    const BATCH_SIZE = 30;
    const observer = _ensureWaveformObserver();

    if (state.segPeaksByAudio) {
        const missingChapters = new Set();
        items.forEach(item => {
            const ch = item.chapter;
            if (!ch) return;
            const url = state.segAllData?.audio_by_chapter?.[String(ch)] || '';
            if (url && !state.segPeaksByAudio[url]) missingChapters.add(ch);
        });
        if (missingChapters.size > 0) {
            const reciter = dom.segReciterSelect.value;
            if (reciter) _fetchPeaks(reciter, [...missingChapters]);
        }
    }

    function renderOneItem(issue) {
        if (type === 'missing_words') {
            const wrapper = document.createElement('div');
            wrapper.className = 'val-card-wrapper';
            const gapLabel = document.createElement('div');
            gapLabel.className = 'val-card-gap-label';
            gapLabel.textContent = issue.msg || 'Missing words between segments';
            wrapper.appendChild(gapLabel);
            const indices = issue.seg_indices || [];
            const segsInWrapper = [];
            indices.forEach(idx => {
                const seg = getSegByChapterIndex(issue.chapter, idx);
                if (seg) {
                    const card = renderErrorCard(seg);
                    wrapper.appendChild(card);
                    segsInWrapper.push({ seg, card });
                }
            });
            const actionsRow = document.createElement('div');
            actionsRow.className = 'val-card-actions';
            if (issue.auto_fix) {
                const fixBtn = document.createElement('button');
                fixBtn.className = 'val-action-btn';
                fixBtn.textContent = 'Auto Fix';
                fixBtn.title = 'Extend segment ref to cover the missing word';
                fixBtn.addEventListener('click', async () => {
                    const af = issue.auto_fix;
                    const seg = getSegByChapterIndex(issue.chapter, af.target_seg_index);
                    if (!seg) return;
                    const oldRef = seg.matched_ref || '';
                    const oldText = seg.matched_text || '';
                    const oldDisplay = seg.display_text || '';
                    const oldConf = seg.confidence;
                    const oldIgnoredCats = seg.ignored_categories ? [...seg.ignored_categories] : null;
                    const segChapter = seg.chapter || issue.chapter;
                    const wasDirty = isIndexDirty(segChapter, seg.index);
                    state._pendingOp = createOp('auto_fix_missing_word', { contextCategory: 'missing_words', fixKind: 'auto_fix' });
                    state._pendingOp.targets_before = [snapshotSeg(seg)];
                    const _autoFixOpId = state._pendingOp.op_id;
                    const newRef = `${af.new_ref_start}-${af.new_ref_end}`;
                    const entry = segsInWrapper.find(s => s.seg === seg);
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
                        if (ops) { const idx = ops.findIndex(o => o.op_id === _autoFixOpId); if (idx !== -1) ops.splice(idx, 1); }
                    });
                    fixBtn.after(undoBtn);
                });
                actionsRow.appendChild(fixBtn);
            }
            if (segsInWrapper.length > 0) addContextToggle(actionsRow, segsInWrapper);
            wrapper.appendChild(actionsRow);
            container.appendChild(wrapper);
        } else if (type === 'missing_verses') {
            const wrapper = document.createElement('div');
            wrapper.className = 'val-card-wrapper';
            const msgLabel = document.createElement('div');
            msgLabel.className = 'val-card-issue-label';
            msgLabel.textContent = issue.msg ? `${issue.verse_key} \u2014 ${issue.msg}` : issue.verse_key;
            wrapper.appendChild(msgLabel);
            const { prev, next } = findMissingVerseBoundarySegments(issue.chapter, issue.verse_key);
            const segsInWrapper = [];
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
            if (issue.msg) { const msgLabel = document.createElement('div'); msgLabel.className = 'val-card-issue-label'; msgLabel.textContent = issue.msg; wrapper.appendChild(msgLabel); }
            const card = renderErrorCard(seg);
            wrapper.appendChild(card);
            if (type === 'boundary_adj' && state.SHOW_BOUNDARY_PHONEMES && (issue.gt_tail || issue.asr_tail)) {
                const textBox = card.querySelector('.seg-text');
                if (textBox) { const tailEl = document.createElement('div'); tailEl.className = 'val-phoneme-tail'; const gt = issue.gt_tail || ''; const asr = issue.asr_tail || ''; tailEl.innerHTML = `<span class="val-tail-label">GT:</span> <span class="val-tail-phonemes">${gt}</span>\n<span class="val-tail-label">ASR:</span> <span class="val-tail-phonemes">${asr}</span>`; textBox.appendChild(tailEl); }
            }
            const actionsRow = document.createElement('div');
            actionsRow.className = 'val-card-actions';
            if ((type === 'boundary_adj' || type === 'cross_verse' || type === 'audio_bleeding' || type === 'repetitions' || type === 'qalqala') || (type === 'low_confidence' && seg.confidence < 1.0)) {
                const ignoreBtn = document.createElement('button');
                ignoreBtn.className = 'val-action-btn ignore-btn';
                const segChapterForBtn = seg.chapter || parseInt(dom.segChapterSelect.value);
                const isDirtySegment = state.segDirtyMap.get(segChapterForBtn)?.indices?.has(seg.index);
                if (_isIgnoredFor(seg, type)) { ignoreBtn.disabled = true; ignoreBtn.textContent = 'Ignored'; wrapper.style.opacity = '0.5'; }
                else if (isDirtySegment) { ignoreBtn.disabled = true; ignoreBtn.textContent = 'Ignore'; ignoreBtn.title = 'Cannot ignore \u2014 this segment already has unsaved edits'; }
                else { ignoreBtn.textContent = 'Ignore'; ignoreBtn.title = 'Dismiss this issue for this category'; }
                ignoreBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (_isIgnoredFor(seg, type)) return;
                    const segChapter = seg.chapter || parseInt(dom.segChapterSelect.value);
                    let ignoreOp;
                    try { ignoreOp = createOp('ignore_issue', { contextCategory: type, fixKind: 'ignore' }); ignoreOp.targets_before = [snapshotSeg(seg)]; ignoreOp.applied_at_utc = ignoreOp.started_at_utc; } catch (err) { console.warn('Ignore: edit history snapshot failed:', err); }
                    if (!seg.ignored_categories) seg.ignored_categories = [];
                    seg.ignored_categories.push(type);
                    delete seg._derived;
                    markDirty(segChapter, seg.index);
                    syncAllCardsForSegment(seg);
                    if (ignoreOp) { try { ignoreOp.targets_after = [snapshotSeg(seg)]; finalizeOp(segChapter, ignoreOp); } catch (err) { console.warn('Ignore: edit history finalize failed:', err); } }
                    ignoreBtn.disabled = true; ignoreBtn.textContent = 'Ignored'; wrapper.style.opacity = '0.5';
                });
                actionsRow.appendChild(ignoreBtn);
            }
            wrapper.appendChild(actionsRow);
            const contextDefault = type === 'failed' || type === 'boundary_adj' || type === 'audio_bleeding' || type === 'repetitions' || type === 'qalqala';
            const nextOnly = type === 'muqattaat' || type === 'qalqala';
            addContextToggle(actionsRow, [{ seg, card }], { defaultOpen: contextDefault, nextOnly });
            container.appendChild(wrapper);
        }
    }

    function processBatch(startIdx) {
        const end = Math.min(startIdx + BATCH_SIZE, items.length);
        for (let i = startIdx; i < end; i++) renderOneItem(items[i]);
        container.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
        if (end < items.length) { state._cardRenderRafId = requestAnimationFrame(() => processBatch(end)); }
        else { state._cardRenderRafId = null; }
    }

    processBatch(0);
}

// ---------------------------------------------------------------------------
// resolveIssueToSegment -- find the segment for a validation issue
// ---------------------------------------------------------------------------

export function resolveIssueToSegment(type, issue) {
    if (issue.seg_index != null && issue.seg_index < 0) return null;
    if (type === 'failed' || type === 'low_confidence' || type === 'boundary_adj' || type === 'cross_verse' || type === 'audio_bleeding' || type === 'repetitions' || type === 'muqattaat' || type === 'qalqala') {
        const seg = getSegByChapterIndex(issue.chapter, issue.seg_index);
        if (seg && issue.ref && seg.matched_ref !== issue.ref) {
            const byRef = getChapterSegments(issue.chapter).find(s => s.matched_ref === issue.ref);
            if (byRef) return byRef;
        }
        return seg;
    }
    if (type === 'errors') {
        const parts = (issue.verse_key || '').split(':');
        const prefix = parts.length >= 2 ? `${parts[0]}:${parts[1]}:` : issue.verse_key;
        const chapterSegs = getChapterSegments(issue.chapter);
        return chapterSegs.find(s => s.matched_ref && s.matched_ref.startsWith(prefix)) || chapterSegs[0] || null;
    }
    return null;
}

// ---------------------------------------------------------------------------
// Context toggle (show/hide prev/next segments around an error card)
// ---------------------------------------------------------------------------

export function addContextToggle(actionsContainer, segsInWrapper, { defaultOpen = false, nextOnly = false } = {}) {
    const ctxBtn = document.createElement('button');
    ctxBtn.className = 'val-action-btn val-action-btn-muted val-ctx-toggle-btn';
    ctxBtn.textContent = 'Show Context';
    let contextShown = false;
    let contextEls = [];

    function showContext() {
        const first = segsInWrapper[0];
        const last = segsInWrapper[segsInWrapper.length - 1];
        const cardParent = first.card.parentNode;
        const { prev } = getAdjacentSegments(first.seg.chapter, first.seg.index);
        const { next } = getAdjacentSegments(last.seg.chapter, last.seg.index);
        if (!nextOnly && prev) { const prevCard = renderErrorCard(prev, { isContext: true, contextLabel: 'Previous' }); cardParent.insertBefore(prevCard, first.card); contextEls.push(prevCard); }
        if (next) { const nextCard = renderErrorCard(next, { isContext: true, contextLabel: 'Next' }); if (last.card.nextSibling) { cardParent.insertBefore(nextCard, last.card.nextSibling); } else { cardParent.insertBefore(nextCard, actionsContainer); } contextEls.push(nextCard); }
        ctxBtn.textContent = 'Hide Context';
        contextShown = true;
    }

    function hideContext() { contextEls.forEach(el => el.remove()); contextEls = []; ctxBtn.textContent = 'Show Context'; contextShown = false; }

    ctxBtn._showContext = showContext;
    ctxBtn._isContextShown = () => contextShown;
    ctxBtn.addEventListener('click', () => { if (contextShown) hideContext(); else showContext(); });
    actionsContainer.appendChild(ctxBtn);
    if (defaultOpen) showContext();
}

export function ensureContextShown(row) {
    const wrapper = row.closest('.val-card-wrapper');
    if (!wrapper) return;
    const actionsRow = wrapper.querySelector('.val-card-actions');
    if (!actionsRow) return;
    for (const btn of actionsRow.children) {
        if (typeof btn._showContext === 'function') { if (!btn._isContextShown()) btn._showContext(); return; }
    }
}

export function _isWrapperContextShown(wrapper) {
    if (!wrapper) return false;
    const actionsRow = wrapper.querySelector('.val-card-actions');
    if (!actionsRow) return false;
    for (const btn of actionsRow.children) { if (typeof btn._isContextShown === 'function') return btn._isContextShown(); }
    return false;
}

// ---------------------------------------------------------------------------
// _getWrapperContextSegs -- internal helper (not currently used externally)
// ---------------------------------------------------------------------------

function _getWrapperContextSegs(wrapper) {
    if (!wrapper) return [];
    return [...wrapper.querySelectorAll('.seg-row-context')];
}

// ---------------------------------------------------------------------------
// _rebuildAccordionAfterSplit
// ---------------------------------------------------------------------------

export function _rebuildAccordionAfterSplit(wrapper, chapter, origSeg, firstHalf, secondHalf) {
    const observer = _ensureWaveformObserver();
    const allSegs = state.segAllData?.segments || state.segData?.segments || [];
    wrapper.querySelectorAll('.seg-row-context').forEach(c => c.remove());
    const mainCards = [...wrapper.querySelectorAll('.seg-row:not(.seg-row-context)')];
    const splitCard = mainCards.find(c => (origSeg.segment_uid && c.dataset.segUid === origSeg.segment_uid) || (parseInt(c.dataset.segChapter) === (origSeg.chapter || chapter) && parseInt(c.dataset.segIndex) === origSeg.index));
    if (splitCard) {
        const f = renderErrorCard(firstHalf);
        const s = renderErrorCard(secondHalf);
        wrapper.insertBefore(f, splitCard);
        wrapper.insertBefore(s, splitCard);
        splitCard.remove();
        [f, s].forEach(c => c.querySelectorAll('canvas[data-needs-waveform]').forEach(cv => observer.observe(cv)));
    } else {
        const actionsRow = wrapper.querySelector('.val-card-actions');
        [renderErrorCard(firstHalf), renderErrorCard(secondHalf)].forEach(c => { actionsRow ? wrapper.insertBefore(c, actionsRow) : wrapper.appendChild(c); c.querySelectorAll('canvas[data-needs-waveform]').forEach(cv => observer.observe(cv)); });
    }
    wrapper.querySelectorAll('.seg-row:not(.seg-row-context)').forEach(card => { const uid = card.dataset.segUid; if (!uid) return; const updatedSeg = allSegs.find(s => s.segment_uid === uid); if (updatedSeg) card.dataset.segIndex = updatedSeg.index; });
    const updatedMain = [...wrapper.querySelectorAll('.seg-row:not(.seg-row-context)')];
    if (updatedMain.length === 0) return;
    const firstMainSeg = resolveSegFromRow(updatedMain[0]);
    const lastMainSeg  = resolveSegFromRow(updatedMain[updatedMain.length - 1]);
    if (firstMainSeg) { const { prev } = getAdjacentSegments(firstMainSeg.chapter || chapter, firstMainSeg.index); if (prev) { const prevCard = renderErrorCard(prev, { isContext: true, contextLabel: 'Previous' }); wrapper.insertBefore(prevCard, updatedMain[0]); prevCard.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c)); } }
    if (lastMainSeg) { const { next } = getAdjacentSegments(lastMainSeg.chapter || chapter, lastMainSeg.index); if (next) { const actionsRow = wrapper.querySelector('.val-card-actions'); const nextCard = renderErrorCard(next, { isContext: true, contextLabel: 'Next' }); actionsRow ? wrapper.insertBefore(nextCard, actionsRow) : wrapper.appendChild(nextCard); nextCard.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c)); } }
}

// ---------------------------------------------------------------------------
// _refreshSiblingCardIndices -- no-op (indices refreshed in rebuild)
// ---------------------------------------------------------------------------

export function _refreshSiblingCardIndices() {
    // Indices are refreshed during _rebuildAccordionAfterSplit
}

// ---------------------------------------------------------------------------
// _rebuildAccordionAfterMerge
// ---------------------------------------------------------------------------

export function _rebuildAccordionAfterMerge(wrapper, chapter, merged, direction) {
    const { prev, next } = getAdjacentSegments(merged.chapter || chapter, merged.index);
    const issueLabel = wrapper.querySelector('.val-card-issue-label');
    wrapper.innerHTML = '';
    if (issueLabel) wrapper.appendChild(issueLabel);
    if (direction === 'prev' && next) { wrapper.appendChild(renderErrorCard(merged)); wrapper.appendChild(renderErrorCard(next, { isContext: true, contextLabel: 'Next' })); }
    else if (direction === 'next' && prev) { wrapper.appendChild(renderErrorCard(prev, { isContext: true, contextLabel: 'Previous' })); wrapper.appendChild(renderErrorCard(merged)); }
    else { wrapper.appendChild(renderErrorCard(merged)); }
    const observer = _ensureWaveformObserver();
    wrapper.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
}
