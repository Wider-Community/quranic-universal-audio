import { get } from 'svelte/store';

import { segCurrentIdx } from '../../stores/segments/chapter';
import { isDirty } from '../../stores/segments/dirty';
import { editMode } from '../../stores/segments/edit';
import { displayedSegments } from '../../stores/segments/filters';
import { savedFilterView, targetSegmentIndex } from '../../stores/segments/navigation';
import {
    activeAudioSource,
    playbackSpeed,
    segAudioElement,
} from '../../stores/segments/playback';
import { savePreviewVisible } from '../../stores/segments/save';
import { LS_KEYS } from '../constants';
import { shouldHandleKey } from '../keyboard-guard';
import { cycleSpeedStore } from '../speed-control';
import { exitEditMode } from './edit-common';
import { beginRefEdit } from './edit-reference';
import { confirmSplit } from './edit-split';
import { confirmTrim } from './edit-trim';
import { getValCardAudioOrNull } from './error-card-audio';
import { _restoreFilterView } from './navigation-actions';
import { onSegPlayClick, playFromSegment } from './playback';
import { confirmSaveFromPreview, hideSavePreview, onSegSaveClick } from './save-actions';

/**
 * Handle a keydown event for the Segments tab.
 *
 * Returns `true` if the event was handled (so the caller can
 * `e.preventDefault()`), `false` otherwise.
 */
export function handleSegmentsKey(e: KeyboardEvent): boolean {
    if (!shouldHandleKey(e, 'segments')) return false;

    switch (e.code) {
        case 'Space':
            onSegPlayClick();
            return true;

        case 'ArrowLeft': {
            const valAudio = getValCardAudioOrNull();
            const mainAudio = get(segAudioElement);
            const el = (get(activeAudioSource) === 'error' && valAudio) ? valAudio : mainAudio;
            if (el) el.currentTime = Math.max(0, el.currentTime - 3);
            return true;
        }

        case 'ArrowRight': {
            const valAudio = getValCardAudioOrNull();
            const mainAudio = get(segAudioElement);
            const el = (get(activeAudioSource) === 'error' && valAudio) ? valAudio : mainAudio;
            if (el) el.currentTime = Math.min(el.duration || 0, el.currentTime + 3);
            return true;
        }

        case 'ArrowUp': {
            const displayed = get(displayedSegments);
            if (!displayed || displayed.length === 0) return true;
            const curIdx = get(segCurrentIdx);
            const curPos = displayed.findIndex(s => s.index === curIdx);
            const prevPos = curPos > 0 ? curPos - 1 : 0;
            const prev = displayed[prevPos];
            if (prev) playFromSegment(prev.index, prev.chapter);
            return true;
        }

        case 'ArrowDown': {
            const displayed = get(displayedSegments);
            if (!displayed || displayed.length === 0) return true;
            const curIdx = get(segCurrentIdx);
            const curPos = displayed.findIndex(s => s.index === curIdx);
            const nextPos = curPos >= 0 && curPos < displayed.length - 1 ? curPos + 1 : (curPos === -1 ? 0 : curPos);
            const nxt = displayed[nextPos];
            if (nxt) playFromSegment(nxt.index, nxt.chapter);
            return true;
        }

        case 'Period':
        case 'Comma': {
            const rate = cycleSpeedStore(playbackSpeed, e.code === 'Period' ? 'up' : 'down', LS_KEYS.SEG_SPEED);
            const valAudio = getValCardAudioOrNull();
            if (valAudio) valAudio.playbackRate = rate;
            return true;
        }

        case 'KeyJ': {
            const curIdx = get(segCurrentIdx);
            if (curIdx >= 0) targetSegmentIndex.set(curIdx);
            return true;
        }

        case 'KeyS': {
            if (isDirty()) {
                onSegSaveClick();
                return true;
            }
            return false;
        }

        case 'Escape':
            if (get(savePreviewVisible)) {
                hideSavePreview();
                return true;
            } else if (get(editMode)) {
                exitEditMode();
                return true;
            } else if (get(savedFilterView)) {
                _restoreFilterView();
                return true;
            }
            return false;

        case 'Enter':
            if (get(savePreviewVisible)) {
                confirmSaveFromPreview();
                return true;
            } else {
                const mode = get(editMode);
                const curIdx = get(segCurrentIdx);
                if (mode && curIdx >= 0) {
                    const displayed = get(displayedSegments);
                    const seg = displayed
                        ? displayed.find(s => s.index === curIdx)
                        : null;
                    if (seg) {
                        if (mode === 'trim') confirmTrim(seg);
                        else if (mode === 'split') confirmSplit(seg);
                        return true;
                    }
                }
            }
            return false;

        case 'KeyE': {
            const curIdx = get(segCurrentIdx);
            if (get(editMode) || curIdx < 0) return false;
            const displayed = get(displayedSegments);
            const seg = displayed
                ? displayed.find(s => s.index === curIdx)
                : null;
            if (seg) { beginRefEdit(seg, null); return true; }
            return false;
        }

        default:
            return false;
    }
}
