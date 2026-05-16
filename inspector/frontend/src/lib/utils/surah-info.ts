/**
 * Shared surah info: fetched once at import time, available across all tabs.
 */

import { fetchJson } from '../api';
import type { SurahInfoResponse } from '../types/api';

let _surahInfo: SurahInfoResponse = {};

export const surahInfoReady = fetchJson<SurahInfoResponse>('/api/surah-info').then((data) => {
    _surahInfo = data;
});

/** Return the cached surah info map. Await `surahInfoReady` before first call. */
export function getSurahInfo(): SurahInfoResponse {
    return _surahInfo;
}

export function surahOptionText(num: number | string): string {
    const info = _surahInfo[String(num)];
    if (!info) return String(num);
    const ar = info.name_ar.replace(/^سُورَةُ\s*/, '');
    return `${num} ${info.name_en} ${ar}`;
}
