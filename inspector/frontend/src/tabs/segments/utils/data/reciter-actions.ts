/**
 * Reciter-level reload action — shared by SegmentsTab's reciter-change
 * handler and the stale-data reload paths in history/save.
 *
 * Fetches the full segment corpus on the critical path, then lets validation,
 * stats, and history populate independently. Chapter-select options come from
 * `segAllData` reactively.
 */

import { get } from 'svelte/store';

import { fetchJson } from '../../../../lib/api';
import { loadQuranRefs, quranRefs } from '../../../../lib/refs/quran-refs';
import type {
    SegAllResponse,
    SegStatsResponse,
    SegValidateResponse,
} from '../../../../lib/types/api';
import { preconnectOrigins } from '../../../../lib/utils/preconnect';
import {
    reciterVbrChapters,
    segAllData,
    selectedChapter,
    selectedReciter,
    selectedVerse,
} from '../../stores/chapter';
import { activeFilters } from '../../stores/filters';
import { savedFilterView } from '../../stores/navigation';
import { setStats } from '../../stores/stats';
import { setValidation } from '../../stores/validation';
import { startHistoryLoad } from '../history/loader';
import { clearPerReciterState } from './clear-per-reciter-state';
import { dkTextForRef } from './references';

/**
 * Hydrate per-segment fields that the server stripped from /seg/all to save
 * wire bytes:
 *   - `audio_url`: re-derived from the top-level `audio_by_chapter` map.
 *     Every consumer expects each Segment to carry its own URL, and shared
 *     string references across segments in the same chapter cost less heap
 *     than separately allocated strings on the wire.
 *   - `matched_text`: re-derived via `dkTextForRef` from the global
 *     `quran-refs.json` bundle. Display already uses `dkTextForRef`; the
 *     in-memory copy is for save round-trip + undo snapshots + merge text
 *     composition. If `quranRefs` is still null (offline / fetch failed),
 *     consumers tolerate empty `matched_text` via `|| ''` fallbacks.
 */
function _hydrateSegAll(all: SegAllResponse): SegAllResponse {
    const audioByChapter = all.audio_by_chapter ?? {};
    const refs = get(quranRefs);
    const dkWords = refs?.dk_words;
    const vwc = refs?.verse_word_counts;
    for (const seg of all.segments) {
        if (!seg.audio_url) {
            seg.audio_url = audioByChapter[String(seg.chapter)] ?? '';
        }
        if (!seg.matched_text && dkWords && vwc) {
            seg.matched_text = dkTextForRef(seg.matched_ref, dkWords, vwc);
        }
    }
    return all;
}

/**
 * Re-fetch data for the currently selected reciter. Used for the stale-data
 * reload paths triggered after undo (from hideHistoryView / hideSavePreview)
 * and from SegmentsTab's reciter-change handler.
 */
export async function reloadCurrentReciter(): Promise<void> {
    const reciter = get(selectedReciter);
    if (!reciter) return;

    selectedChapter.set('');
    selectedVerse.set('');
    activeFilters.set([]);
    savedFilterView.set(null);
    clearPerReciterState();

    // Kick off the refs load in parallel; hydration tolerates a null
    // ``quranRefs`` (matched_text stays empty for those segs and consumer
    // fallbacks via dkTextForRef at render time fill the gap).
    const allPromise = Promise.all([
        fetchJson<SegAllResponse>(`/api/seg/all/${reciter}`),
        loadQuranRefs(),
    ])
        .then(([all]) => {
            if (get(selectedReciter) !== reciter) return;
            if ('error' in all) {
                console.error('Error loading all segments:', (all as any).error);
                return;
            }
            segAllData.set(_hydrateSegAll(all));
            reciterVbrChapters.set(new Set(all.reciter_vbr_chapters ?? []));
            preconnectOrigins(Object.values(all.audio_by_chapter ?? {}));
        })
        .catch((e) => console.error('Error loading all segments:', e));

    void fetchJson<SegValidateResponse>(`/api/seg/validate/${reciter}`)
        .then((data) => {
            if (get(selectedReciter) === reciter) setValidation(data);
        })
        .catch((e) => console.error('Error loading validation:', e));

    void fetchJson<SegStatsResponse>(`/api/seg/stats/${reciter}`)
        .then((data) => {
            if (get(selectedReciter) === reciter && !data.error) setStats(data);
        })
        .catch((e) => console.error('Error loading stats:', e));

    // Background only. Opening History awaits the same in-flight promise and
    // then hydrates persisted waveform peaks.
    void startHistoryLoad(reciter);

    await allPromise;
}
