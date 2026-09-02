/**
 * Playhead -> active word bridge for samples with word timings. Called from
 * the playback rAF ticks; the identity-guarded store setter keeps rows idle
 * until the word actually changes.
 */

import { get } from 'svelte/store';

import { playingSegmentIndex } from '../../stores/playback';
import { isSampleMode, sampleWords, setPlayingWord } from '../../stores/samples';
import { getSegByChapterIndex } from '../../stores/chapter';
import { activeWordLocation } from './words';

export function updatePlayingWord(timeMs: number): void {
    if (!get(isSampleMode)) return;
    const active = get(playingSegmentIndex);
    const uid = active ? getSegByChapterIndex(active.chapter, active.index)?.segment_uid : null;
    const words = uid ? get(sampleWords)[uid] : undefined;
    if (!uid || !words) {
        setPlayingWord(null);
        return;
    }
    const location = activeWordLocation(words, timeMs);
    setPlayingWord(location ? { uid, location } : null);
}
