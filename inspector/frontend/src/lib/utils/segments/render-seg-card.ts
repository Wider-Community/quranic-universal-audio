import { getAdjacentSegments } from '../../../segments/data';
import { _addVerseMarkers, formatRef, formatTimeMs } from '../../../segments/references';
import { dom, isIndexDirty } from '../../../segments/state';
import type { Segment } from '../../../types/domain';
import { getConfClass } from './conf-class';

/** Options consumed by `renderSegCard`. */
export interface RenderSegCardOptions {
    showChapter?: boolean;
    showPlayBtn?: boolean;
    showGotoBtn?: boolean;
    isContext?: boolean;
    contextLabel?: string;
    missingWordSegIndices?: Set<number> | null;
    readOnly?: boolean;
}

/**
 * Render a single segment card (.seg-row).
 */
export function renderSegCard(seg: Segment, options: RenderSegCardOptions = {}): HTMLDivElement {
    const {
        showChapter = false,
        showPlayBtn = false,
        showGotoBtn = false,
        isContext = false,
        contextLabel = '',
        missingWordSegIndices = null,
        readOnly = false,
    } = options;

    const chapterForDirty = seg.chapter ?? parseInt(dom.segChapterSelect.value);
    const row = document.createElement('div');
    row.className = 'seg-row' + (!readOnly && isIndexDirty(chapterForDirty, seg.index) ? ' dirty' : '') + (isContext ? ' seg-row-context' : '');
    row.dataset.segIndex = String(seg.index);
    if (seg.chapter != null) row.dataset.segChapter = String(seg.chapter);
    if (seg.segment_uid) row.dataset.segUid = seg.segment_uid;

    if (readOnly) {
        row.dataset.histTimeStart = String(seg.time_start);
        row.dataset.histTimeEnd = String(seg.time_end);
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

        const { prev: adjPrev, next: adjNext } = getAdjacentSegments(seg.chapter ?? 0, seg.index);

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
    confSpan.textContent = seg.matched_ref ? ((seg.confidence ?? 0) * 100).toFixed(1) + '%' : 'FAIL';
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

/** Update a single .seg-row card in-place. */
export function updateSegCard(row: HTMLElement, seg: Segment): void {
    row.classList.add('dirty');

    const ignoreBtn: HTMLButtonElement | null =
        row.querySelector<HTMLButtonElement>('.val-action-btn.ignore-btn')
        ?? row.closest('.val-card-wrapper')?.querySelector<HTMLButtonElement>('.val-action-btn.ignore-btn')
        ?? null;
    if (ignoreBtn && !ignoreBtn.disabled) {
        ignoreBtn.disabled = true;
        ignoreBtn.title = 'Cannot ignore -- this segment already has unsaved edits';
    }

    const confClass = getConfClass(seg);
    const textBox = row.querySelector<HTMLElement>('.seg-text');
    if (textBox) textBox.className = `seg-text ${confClass}`;

    const refSpan = row.querySelector<HTMLElement>('.seg-text-ref');
    if (refSpan) refSpan.textContent = formatRef(seg.matched_ref);

    const confSpan = row.querySelector<HTMLElement>('.seg-text-conf');
    if (confSpan) {
        confSpan.className = `seg-text-conf ${confClass}`;
        confSpan.textContent = seg.matched_ref ? ((seg.confidence ?? 0) * 100).toFixed(1) + '%' : 'FAIL';
    }

    const body = row.querySelector<HTMLElement>('.seg-text-body');
    if (body) body.textContent = _addVerseMarkers(seg.display_text || seg.matched_text, seg.matched_ref) || '(alignment failed)';

    const durSpan = row.querySelector<HTMLElement>('.seg-text-duration');
    if (durSpan) {
        const durSec = (seg.time_end - seg.time_start) / 1000;
        durSpan.textContent = durSec.toFixed(1) + 's';
        durSpan.title = `${formatTimeMs(seg.time_start)} \u2013 ${formatTimeMs(seg.time_end)}`;
    }
}

/** Sync all .seg-row cards matching this segment across the entire page. */
export function syncAllCardsForSegment(seg: Segment): void {
    document.querySelectorAll<HTMLElement>(
        `.seg-row[data-seg-chapter="${seg.chapter}"][data-seg-index="${seg.index}"]`,
    ).forEach((row) => {
        if (!row.classList.contains('seg-row-context')) {
            updateSegCard(row, seg);
        }
    });
}
