// @ts-nocheck — removed per-file as each module is typed in Phases 4+
/**
 * Shared surah info: fetched once at import time, available across all tabs.
 *
 * `surahInfo` is a live `let` binding — importers see the updated value
 * after the fetch resolves because ES module live bindings work by reference
 * to the exporting module's variable.
 */

import { fetchJson } from './api';
import type { SurahInfoResponse } from '../types/api';

export let surahInfo: SurahInfoResponse = {};

export const surahInfoReady = fetchJson<SurahInfoResponse>('/api/surah-info').then((data) => {
    surahInfo = data;
});

export function surahOptionText(num) {
    const info = surahInfo[String(num)];
    if (!info) return String(num);
    const ar = info.name_ar.replace(/^سُورَةُ\s*/, '');
    return `${num} ${info.name_en} ${ar}`;
}
