import { get } from 'svelte/store';

import { SIGN_IN_MESSAGES } from '../../../lib/sign-in-messages';
import { editingMode } from '../../../lib/stores/editing-mode';
import { openGuidesGate } from '../../../lib/stores/guides-gate';
import { openSignInModal } from '../../../lib/stores/sign-in-modal';
import { LS_KEYS } from '../../../lib/utils/constants';
import { shouldHandleKey } from '../../../lib/utils/keyboard-guard';
import { cycleSpeedStore, SEGMENTS_SPEEDS } from '../../../lib/utils/speed-control';
import { segCurrentIdx, selectedChapter } from '../stores/chapter';
import { isDirty } from '../stores/dirty';
import { editMode } from '../stores/edit';
import { displayedSegments } from '../stores/filters';
import { savedFilterView, targetSegmentIndex } from '../stores/navigation';
import {
    playbackSpeed,
    segPort,
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
 * Honour the same edit gate as the `editGate` action for keyboard-initiated
 * edits — clicks go through `editGate`, but keyboard shortcuts (E/S/Enter) would
 * otherwise bypass it. Returns `true` when editing is blocked (the caller must
 * NOT perform the mutation) and surfaces the right prompt: the sign-in modal for
 * anonymous, the guide onboarding modal for `guides_unread`. Other view reasons
 * (wrong-assignee, marked_ready, …) just block silently — the buttons already
 * explain those via the popover, and a keyboard path has no anchor element.
 */
function gateKeyboardEdit(): boolean {
    const mode = get(editingMode);
    if (mode.kind !== 'view') return false; // editable — let the edit proceed
    if (mode.viewReason === 'unauthenticated') {
        openSignInModal(null, SIGN_IN_MESSAGES.edit);
    } else if (mode.viewReason === 'guides_unread') {
        openGuidesGate('gate');
    }
    return true;
}

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
            // Port owns CBR vs VBR offset translation — `currentTimeMs()`
            // returns file-absolute regardless, and `seek()` writes file-
            // absolute back. Under VBR this previously wrote file-absolute
            // ms onto a clip-relative element (broken nudge — fixed by the
            // port indirection). Negative seeks clamp inside the port.
            segPort.seek(segPort.currentTimeMs() - KEY_SEEK_SECONDS * 1000);
            return true;
        }

        case 'ArrowRight': {
            // Audio element clamps over-shoots to its own duration (which
            // for VBR clips is the clip span, not the file span — that's
            // the expected behavior: you can't nudge past the loaded clip).
            segPort.seek(segPort.currentTimeMs() + KEY_SEEK_SECONDS * 1000);
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
            const rate = cycleSpeedStore(playbackSpeed, e.code === 'Period' ? 'up' : 'down', LS_KEYS.SEG_SPEED, SEGMENTS_SPEEDS);
            // Write through the port. The main audio must NOT be updated
            // via a reactive `$: audioEl.playbackRate = $playbackSpeed`
            // block — on Period/Comma that reactive fires while the keydown
            // is still being processed and races with Svelte's DOM update
            // for `<select value={$playbackSpeed}>`, which steals focus
            // onto the <select> and drops the ongoing audio playback.
            segPort.setPlaybackRate(rate);
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
                if (gateKeyboardEdit()) return true;
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
                if (gateKeyboardEdit()) return true;
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
                        if (gateKeyboardEdit()) return true;
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
            if (seg) {
                // The live keyboard bypass: E begins a ref-edit that the
                // (use:editGate) buttons would have blocked. Gate it too.
                if (gateKeyboardEdit()) return true;
                beginRefEdit(seg, null);
                return true;
            }
            return false;
        }

        default:
            return false;
    }
}
