import { get } from 'svelte/store';

import { dom } from '../../segments-state';
import { segAllReciters } from '../../stores/segments/chapter';

/** Returns true if the current reciter uses by_surah audio source. */
export function _isCurrentReciterBySurah(): boolean {
    const reciter = dom.segReciterSelect.value;
    const info = get(segAllReciters).find(r => r.slug === reciter);
    return !!(info && info.audio_source && info.audio_source.startsWith('by_surah'));
}
