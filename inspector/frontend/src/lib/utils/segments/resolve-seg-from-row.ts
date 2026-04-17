import type { Segment } from '../../../types/domain';
import { state } from '../../segments-state';
import { getSegByChapterIndex } from '../../stores/segments/chapter';

/** Resolve a segment object from a .seg-row element. */
export function resolveSegFromRow(row: HTMLElement | null | undefined): Segment | null {
    if (!row) return null;
    const idx = parseInt(row.dataset.segIndex ?? '');
    const chapter = parseInt(row.dataset.segChapter ?? '');
    if (row.dataset.histTimeStart !== undefined) {
        // History-row synthetic segment — carries only the fields the waveform
        // / playback code reads from read-only rows.
        const synth: Segment = {
            chapter,
            index: idx,
            entry_idx: 0,
            time_start: parseFloat(row.dataset.histTimeStart),
            time_end: parseFloat(row.dataset.histTimeEnd ?? '0'),
            audio_url: row.dataset.histAudioUrl || '',
            matched_ref: '',
            matched_text: '',
            display_text: '',
            confidence: 0,
        };
        return synth;
    }
    const fromMap = state._segIndexMap?.get(`${chapter}:${idx}`);
    if (fromMap) return fromMap;
    if (chapter) return getSegByChapterIndex(chapter, idx);
    return null;
}
