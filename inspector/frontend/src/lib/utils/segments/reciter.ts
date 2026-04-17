import { dom, state } from '../../segments-state';

/** Returns true if the current reciter uses by_surah audio source. */
export function _isCurrentReciterBySurah(): boolean {
    const reciter = dom.segReciterSelect.value;
    const info = state.segAllReciters.find(r => r.slug === reciter);
    return !!(info && info.audio_source && info.audio_source.startsWith('by_surah'));
}
