import { get } from 'svelte/store';

import { LS_KEYS } from '../../../lib/utils/constants';
import { shouldHandleKey } from '../../../lib/utils/keyboard-guard';
import { cycleSpeedStore } from '../../../lib/utils/speed-control';
import { segCurrentIdx, selectedChapter } from '../stores/chapter';
import { isDirty } from '../stores/dirty';
import { editMode } from '../stores/edit';
import { displayedSegments } from '../stores/filters';
import { savedFilterView, targetSegmentIndex } from '../stores/navigation';
import {
    playbackSpeed,
    segAudioElement,
} from '../stores/playback';
import { savePreviewVisible } from '../stores/save';
import { KEY_SEEK_SECONDS } from './constants';
import { _restoreFilterView } from './data/navigation-actions';
import { exitEditMode, getEditingSeg } from './edit/common';
import { beginRefEdit } from './edit/reference';
import { confirmSplit } from './edit/split';
import { confirmTrim } from './edit/trim';
import { onSegPlayClick, playFromSegment } from './playback/playback';
import { confirmSaveFromPreview, hideSavePreview, onSegSaveClick } from './save/actions';

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
            const el = get(segAudioElement);
            if (el) el.currentTime = Math.max(0, el.currentTime - KEY_SEEK_SECONDS);
            return true;
        }

        case 'ArrowRight': {
            const el = get(segAudioElement);
            if (el) el.currentTime = Math.min(el.duration || 0, el.currentTime + KEY_SEEK_SECONDS);
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
            // Write the new rate directly to both audio elements. The main
            // audio must NOT be updated via a reactive `$: audioEl.playbackRate
            // = $playbackSpeed` block — on Period/Comma that reactive fires
            // while the keydown is still being processed and races with
            // Svelte's DOM update for `<select value={$playbackSpeed}>`, which
            // steals focus onto the <select> and drops the ongoing audio
            // playback. Direct set here keeps audio and store in sync without
            // routing through Svelte's update cycle.
            const mainAudio = get(segAudioElement);
            if (mainAudio) mainAudio.playbackRate = rate;
            return true;
        }

        case 'KeyJ': {
            const curIdx = get(segCurrentIdx);
            const chStr = get(selectedChapter);
            const curChapter = parseInt(chStr);
            if (curIdx >= 0 && Number.isFinite(curChapter)) {
                targetSegmentIndex.set({ chapter: curChapter, index: curIdx });
            }
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
                if (mode) {
                    // Resolve via the active edit UID rather than the main-list
                    // index — accordion-initiated edits from a non-current
                    // chapter aren't in `displayedSegments`.
                    const seg = getEditingSeg();
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
