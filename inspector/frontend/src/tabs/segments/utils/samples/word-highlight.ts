/**
 * Playhead -> active word bridge for samples with word timings. Called from
 * the playback rAF ticks; the identity-guarded store setter keeps rows idle
 * until the word actually changes.
 */

import { get } from 'svelte/store';

import { playingSegmentIndex } from '../../stores/playback';
import { isSampleMode, setPlayingWord } from '../../stores/samples';
import { getSegByChapterIndex } from '../../stores/chapter';
import { activeWordLocation } from './words';

export function updatePlayingWord(timeMs: number): void {
    if (!get(isSampleMode)) return;
    const active = get(playingSegmentIndex);
    const seg = active ? getSegByChapterIndex(active.chapter, active.index) : null;
    const uid = seg?.segment_uid;
    const words = seg?.word_timings;
    if (!uid || !words?.length) {
        setPlayingWord(null);
        return;
    }
    const location = activeWordLocation(words, timeMs);
    setPlayingWord(location ? { uid, location } : null);
}
