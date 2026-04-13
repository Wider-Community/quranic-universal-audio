/**
 * Keyboard handler for the Segments tab.
 * Uses registerHandler pattern for edit/save functions.
 */

import { getActiveTab } from '../main';
import { LS_KEYS } from '../shared/constants';
import { cycleSpeed } from '../shared/speed-control';
import { _restoreFilterView } from './navigation';
import { onSegPlayClick,playFromSegment } from './playback/index';
import type { SegKeyboardHandlerRegistry } from './registry';
import { dom, isDirty,state } from './state';

// Handler registry — populated exactly once from segments/index.ts during
// DOMContentLoaded, after which every slot is guaranteed non-null.
let _handlers: SegKeyboardHandlerRegistry = null as unknown as SegKeyboardHandlerRegistry;
export function registerAllSegKeyboardHandlers(handlers: SegKeyboardHandlerRegistry): void {
    _handlers = handlers;
}

export function handleSegKeydown(e: KeyboardEvent): void {
    const target = e.target as Element | null;
    if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) return;
    if (getActiveTab() !== 'segments') return;

    switch (e.code) {
        case 'Space':
            e.preventDefault();
            onSegPlayClick();
            break;
        case 'ArrowLeft': {
            e.preventDefault();
            const el = (state._activeAudioSource === 'error' && state.valCardAudio) ? state.valCardAudio : dom.segAudioEl;
            el.currentTime = Math.max(0, el.currentTime - 3);
            break;
        }
        case 'ArrowRight': {
            e.preventDefault();
            const el = (state._activeAudioSource === 'error' && state.valCardAudio) ? state.valCardAudio : dom.segAudioEl;
            el.currentTime = Math.min(el.duration || 0, el.currentTime + 3);
            break;
        }
        case 'ArrowUp': {
            e.preventDefault();
            if (!state.segDisplayedSegments || state.segDisplayedSegments.length === 0) break;
            const curPos = state.segDisplayedSegments.findIndex(s => s.index === state.segCurrentIdx);
            const prevPos = curPos > 0 ? curPos - 1 : 0;
            const prev = state.segDisplayedSegments[prevPos];
            if (prev) playFromSegment(prev.index, prev.chapter);
            break;
        }
        case 'ArrowDown': {
            e.preventDefault();
            if (!state.segDisplayedSegments || state.segDisplayedSegments.length === 0) break;
            const curPos = state.segDisplayedSegments.findIndex(s => s.index === state.segCurrentIdx);
            const nextPos = curPos >= 0 && curPos < state.segDisplayedSegments.length - 1 ? curPos + 1 : (curPos === -1 ? 0 : curPos);
            const nxt = state.segDisplayedSegments[nextPos];
            if (nxt) playFromSegment(nxt.index, nxt.chapter);
            break;
        }
        case 'Period':
        case 'Comma': {
            e.preventDefault();
            cycleSpeed(dom.segSpeedSelect, dom.segAudioEl, e.code === 'Period' ? 'up' : 'down', LS_KEYS.SEG_SPEED);
            if (state.valCardAudio) state.valCardAudio.playbackRate = parseFloat(dom.segSpeedSelect.value);
            break;
        }
        case 'KeyJ': {
            e.preventDefault();
            const row = dom.segListEl.querySelector<HTMLElement>(`.seg-row[data-seg-index="${state.segCurrentIdx}"]`);
            if (row) row.scrollIntoView({ behavior: 'smooth', block: 'center' });
            break;
        }
        case 'KeyS': {
            if (isDirty()) {
                e.preventDefault();
                _handlers.onSegSaveClick();
            }
            break;
        }
        case 'Escape':
            if (!dom.segSavePreview.hidden) {
                e.preventDefault();
                _handlers.hideSavePreview();
            } else if (state.segEditMode) {
                e.preventDefault();
                _handlers.exitEditMode();
            } else if (state._segSavedFilterView) {
                e.preventDefault();
                _restoreFilterView();
            }
            break;

        case 'Enter':
            if (!dom.segSavePreview.hidden) {
                e.preventDefault();
                _handlers.confirmSaveFromPreview();
            } else if (state.segEditMode && state.segCurrentIdx >= 0) {
                e.preventDefault();
                const seg = state.segDisplayedSegments
                    ? state.segDisplayedSegments.find(s => s.index === state.segCurrentIdx)
                    : null;
                if (seg) {
                    if (state.segEditMode === 'trim') _handlers.confirmTrim(seg);
                    else if (state.segEditMode === 'split') _handlers.confirmSplit(seg);
                }
            }
            break;

        case 'KeyE': {
            if (state.segEditMode || state.segCurrentIdx < 0) break;
            e.preventDefault();
            const row = dom.segListEl.querySelector<HTMLElement>(`.seg-row[data-seg-index="${state.segCurrentIdx}"]`);
            const seg = state.segDisplayedSegments
                ? state.segDisplayedSegments.find(s => s.index === state.segCurrentIdx)
                : null;
            if (row && seg) {
                const refSpan = row.querySelector<HTMLElement>('.seg-text-ref');
                if (refSpan) _handlers.startRefEdit(refSpan, seg, row);
            }
            break;
        }
    }
}
