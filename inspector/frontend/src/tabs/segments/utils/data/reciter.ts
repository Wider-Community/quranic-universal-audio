import { get } from 'svelte/store';

import { segAllReciters, selectedReciter } from '../../stores/chapter';

/** Returns true if the current reciter uses by_surah audio source. */
export function _isCurrentReciterBySurah(): boolean {
    const reciter = get(selectedReciter);
    const info = get(segAllReciters).find(r => r.slug === reciter);
    return !!(info && info.audio_source && info.audio_source.startsWith('by_surah'));
}
