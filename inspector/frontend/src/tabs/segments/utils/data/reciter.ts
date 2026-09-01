import { get } from 'svelte/store';

import { segAllReciters, selectedReciter } from '../../stores/chapter';
import { isSampleSlug } from '../../stores/samples';

/** True when the current reciter serves one MP3 per chapter (by_surah).
 *  False for by_ayah (per-verse MP3s) and for unknown reciters.
 *
 *  Reads `audio_category` from the catalog-backed `/api/seg/reciters`
 *  payload. The previous implementation gated on `audio_source` (the
 *  *channel* — `mp3quran`, `qul`, etc.) with a `startsWith('by_surah')`
 *  check that never matched any real value, so this function silently
 *  returned false for every reciter and the CBR proxy-wrap downstream
 *  never fired. */
export function _isCurrentReciterBySurah(): boolean {
    const reciter = get(selectedReciter);
    if (isSampleSlug(reciter)) return true; // one MP3 per sample, served by the proxy
    const info = get(segAllReciters).find(r => r.slug === reciter);
    return info?.audio_category === 'by_surah';
}
