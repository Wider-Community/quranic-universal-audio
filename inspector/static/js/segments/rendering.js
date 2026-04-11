/**
 * Segment card rendering -- renderSegCard, renderSegList, and card update helpers.
 */

import { state, dom, isIndexDirty } from './state.js';
import { formatRef, formatTimeMs, _addVerseMarkers } from './references.js';
import { getAdjacentSegments, getSegByChapterIndex } from './data.js';
import { _ensureWaveformObserver } from './waveform.js';

export function getConfClass(seg) {
    if (!seg.matched_ref) return 'conf-fail';
    if (seg.confidence >= 0.80) return 'conf-high';
    if (seg.confidence >= 0.60) return 'conf-mid';
    return 'conf-low';
}

/**
 * Render a single segment card (.seg-row).
 */
export function renderSegCard(seg, options = {}) {
    const {
        showChapter = false,
        showPlayBtn = false,
        showGotoBtn = false,
        isContext = false,
        contextLabel = '',
        missingWordSegIndices = null,
        readOnly = false,
    } = options;

    const row = document.createElement('div');
    row.className = 'seg-row' + (!readOnly && isIndexDirty(seg.chapter || parseInt(dom.segChapterSelect.value), seg.index) ? ' dirty' : '') + (isContext ? ' seg-row-context' : '');
    row.dataset.segIndex = seg.index;
    row.dataset.segChapter = seg.chapter;
    if (seg.segment_uid) row.dataset.segUid = seg.segment_uid;

    if (readOnly) {
        row.dataset.histTimeStart = seg.time_start;
        row.dataset.histTimeEnd = seg.time_end;
        if (seg.audio_url) row.dataset.histAudioUrl = seg.audio_url;
    }

    if (!isContext && !readOnly) {
        const playCol = document.createElement('div');
        playCol.className = 'seg-play-col';

        const playBtn = document.createElement('button');
        playBtn.className = 'btn btn-sm seg-card-play-btn';
        playBtn.textContent = '\u25B6';
        playBtn.title = 'Play segment audio';
        playCol.appendChild(playBtn);

        if (showGotoBtn) {
            const gotoBtn = document.createElement('button');
            gotoBtn.className = 'btn btn-sm seg-card-goto-btn';
            gotoBtn.textContent = 'Go to';
            playCol.appendChild(gotoBtn);
        }

        row.appendChild(playCol);
    }

    const leftCol = document.createElement('div');
    leftCol.className = 'seg-left';

    const canvas = document.createElement('canvas');
    canvas.width = 380;
    canvas.height = 60;
    canvas.setAttribute('data-needs-waveform', '');

    if (readOnly && showPlayBtn) {
        const playBtn = document.createElement('button');
        playBtn.className = 'btn btn-sm seg-card-play-btn';
        playBtn.textContent = '\u25B6';
        playBtn.title = 'Play segment audio';
        leftCol.appendChild(playBtn);
        leftCol.appendChild(canvas);
    } else {
        leftCol.appendChild(canvas);
    }

    if (!isContext && !readOnly) {
        const actions = document.createElement('div');
        actions.className = 'seg-actions';

        const trimBtn = document.createElement('button');
        trimBtn.className = 'btn btn-sm btn-adjust';
        trimBtn.textContent = 'Adjust';

        const { prev: adjPrev, next: adjNext } = getAdjacentSegments(seg.chapter, seg.index);

        const mergePrevBtn = document.createElement('button');
        mergePrevBtn.className = 'btn btn-sm btn-merge-prev';
        mergePrevBtn.textContent = 'Merge \u2191';
        if (!adjPrev) {
            mergePrevBtn.disabled = true;
            mergePrevBtn.title = 'No previous segment to merge with';
        } else if (adjPrev.audio_url && seg.audio_url && adjPrev.audio_url !== seg.audio_url) {
            mergePrevBtn.disabled = true;
            mergePrevBtn.title = 'Cannot merge segments from different audio files';
        }

        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'btn btn-sm btn-delete';
        deleteBtn.textContent = 'Delete';

        const splitBtn = document.createElement('button');
        splitBtn.className = 'btn btn-sm btn-split';
        splitBtn.textContent = 'Split';

        const mergeNextBtn = document.createElement('button');
        mergeNextBtn.className = 'btn btn-sm btn-merge-next';
        mergeNextBtn.textContent = 'Merge \u2193';
        if (!adjNext) {
            mergeNextBtn.disabled = true;
            mergeNextBtn.title = 'No next segment to merge with';
        } else if (adjNext.audio_url && seg.audio_url && adjNext.audio_url !== seg.audio_url) {
            mergeNextBtn.disabled = true;
            mergeNextBtn.title = 'Cannot merge segments from different audio files';
        }

        const editRefBtn = document.createElement('button');
        editRefBtn.className = 'btn btn-sm btn-edit-ref';
        editRefBtn.textContent = 'Edit Ref';

        actions.append(trimBtn, mergePrevBtn, deleteBtn, splitBtn, mergeNextBtn, editRefBtn);
        leftCol.appendChild(actions);
    } else if (isContext) {
        const playBtn = document.createElement('button');
        playBtn.className = 'btn btn-sm seg-card-play-btn';
        playBtn.hidden = true;
        leftCol.appendChild(playBtn);
    }

    row.appendChild(leftCol);

    const textBox = document.createElement('div');
    const confClass = getConfClass(seg);
    textBox.className = `seg-text ${confClass}`;

    const metaCol = document.createElement('div');
    metaCol.className = 'seg-text-meta';

    const header = document.createElement('div');
    header.className = 'seg-text-header';

    const indexSpan = document.createElement('span');
    indexSpan.className = 'seg-text-index';
    indexSpan.textContent = showChapter ? `${seg.chapter}:#${seg.index}` : `#${seg.index}`;

    const sep1 = document.createElement('span');
    sep1.className = 'seg-text-sep';
    sep1.textContent = '|';

    const refSpan = document.createElement('span');
    refSpan.className = 'seg-text-ref';
    refSpan.textContent = formatRef(seg.matched_ref);

    const sep2 = document.createElement('span');
    sep2.className = 'seg-text-sep';
    sep2.textContent = '|';

    const durSpan = document.createElement('span');
    durSpan.className = 'seg-text-duration';
    const durSec = (seg.time_end - seg.time_start) / 1000;
    durSpan.textContent = durSec.toFixed(1) + 's';
    durSpan.title = `${formatTimeMs(seg.time_start)} \u2013 ${formatTimeMs(seg.time_end)}`;

    header.append(indexSpan, sep1, refSpan, sep2, durSpan);
    if (missingWordSegIndices && missingWordSegIndices.has(seg.index)) {
        const tag = document.createElement('span');
        tag.className = 'seg-tag seg-tag-missing';
        tag.textContent = 'Missing words';
        header.appendChild(tag);
    }
    metaCol.appendChild(header);

    const confSpan = document.createElement('span');
    confSpan.className = `seg-text-conf ${confClass}`;
    confSpan.textContent = seg.matched_ref ? (seg.confidence * 100).toFixed(1) + '%' : 'FAIL';
    metaCol.appendChild(confSpan);

    if (contextLabel) {
        const lbl = document.createElement('div');
        lbl.className = 'seg-text-label';
        lbl.textContent = contextLabel;
        metaCol.appendChild(lbl);
    }

    textBox.appendChild(metaCol);

    const body = document.createElement('div');
    body.className = 'seg-text-body';
    body.textContent = _addVerseMarkers(seg.display_text || seg.matched_text, seg.matched_ref) || '(alignment failed)';
    textBox.appendChild(body);

    row.appendChild(textBox);
    return row;
}

export function renderSegList(segments) {
    state._prevHighlightedRow = null; state._prevHighlightedIdx = -1;
    state._prevPlayheadRow = null; state._currentPlayheadRow = null; state._prevPlayheadIdx = -1;
    dom.segListEl.innerHTML = '';
    if (!segments || segments.length === 0) {
        dom.segListEl.innerHTML = '<div class="seg-loading">No segments to display</div>';
        return;
    }

    const missingWordSegIndices = new Set();
    if (state.segValidation && state.segValidation.missing_words) {
        const chapter = parseInt(dom.segChapterSelect.value) || 0;
        state.segValidation.missing_words.forEach(mw => {
            if (mw.chapter === chapter && mw.seg_indices) {
                mw.seg_indices.forEach(idx => missingWordSegIndices.add(idx));
            }
        });
    }

    const fragment = document.createDocumentFragment();
    const observer = _ensureWaveformObserver();

    segments.forEach((seg, displayIdx) => {
        const row = renderSegCard(seg, { missingWordSegIndices });

        if (seg._isNeighbour) row.classList.add('seg-neighbour');
        fragment.appendChild(row);

        if (seg.silence_after_ms != null) {
            const nextDisplayed = segments[displayIdx + 1];
            if (nextDisplayed && nextDisplayed.index === seg.index + 1) {
                const wrapper = document.createElement('div');
                wrapper.className = 'seg-silence-gap-wrapper';
                const gapDiv = document.createElement('div');
                gapDiv.className = 'seg-silence-gap';
                gapDiv.textContent = `\u23F8 ${Math.round(seg.silence_after_ms)}ms (raw: ${Math.round(seg.silence_after_raw_ms)}ms)`;
                wrapper.appendChild(gapDiv);
                fragment.appendChild(wrapper);
            }
        }
    });

    dom.segListEl.appendChild(fragment);
    dom.segListEl.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
}

/** Update a single .seg-row card in-place. */
export function updateSegCard(row, seg) {
    row.classList.add('dirty');

    const ignoreBtn = row.querySelector('.val-action-btn.ignore-btn')
        || row.closest('.val-card-wrapper')?.querySelector('.val-action-btn.ignore-btn');
    if (ignoreBtn && !ignoreBtn.disabled) {
        ignoreBtn.disabled = true;
        ignoreBtn.title = 'Cannot ignore -- this segment already has unsaved edits';
    }

    const confClass = getConfClass(seg);
    const textBox = row.querySelector('.seg-text');
    if (textBox) textBox.className = `seg-text ${confClass}`;

    const refSpan = row.querySelector('.seg-text-ref');
    if (refSpan) refSpan.textContent = formatRef(seg.matched_ref);

    const confSpan = row.querySelector('.seg-text-conf');
    if (confSpan) {
        confSpan.className = `seg-text-conf ${confClass}`;
        confSpan.textContent = seg.matched_ref ? (seg.confidence * 100).toFixed(1) + '%' : 'FAIL';
    }

    const body = row.querySelector('.seg-text-body');
    if (body) body.textContent = _addVerseMarkers(seg.display_text || seg.matched_text, seg.matched_ref) || '(alignment failed)';

    const durSpan = row.querySelector('.seg-text-duration');
    if (durSpan) {
        const durSec = (seg.time_end - seg.time_start) / 1000;
        durSpan.textContent = durSec.toFixed(1) + 's';
        durSpan.title = `${formatTimeMs(seg.time_start)} \u2013 ${formatTimeMs(seg.time_end)}`;
    }
}

/** Sync all .seg-row cards matching this segment across the entire page. */
export function syncAllCardsForSegment(seg) {
    document.querySelectorAll(
        `.seg-row[data-seg-chapter="${seg.chapter}"][data-seg-index="${seg.index}"]`
    ).forEach(row => {
        if (!row.classList.contains('seg-row-context')) {
            updateSegCard(row, seg);
        }
    });
}

/** Resolve a segment object from a .seg-row element. */
export function resolveSegFromRow(row) {
    if (!row) return null;
    const idx = parseInt(row.dataset.segIndex);
    const chapter = parseInt(row.dataset.segChapter);
    if (row.dataset.histTimeStart !== undefined) {
        return {
            chapter, index: idx,
            time_start: parseFloat(row.dataset.histTimeStart),
            time_end: parseFloat(row.dataset.histTimeEnd),
            audio_url: row.dataset.histAudioUrl || '',
            matched_ref: '', matched_text: '', confidence: 0,
        };
    }
    const fromMap = state._segIndexMap?.get(`${chapter}:${idx}`);
    if (fromMap) return fromMap;
    if (chapter) return getSegByChapterIndex(chapter, idx);
    return null;
}

/** Find the card canvas that's currently in edit mode. */
export function _getEditCanvas() {
    const row = document.querySelector('.seg-row.seg-edit-target');
    return row?.querySelector('canvas') || null;
}
