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
import { _fetchCacheStatus, _rewriteAudioUrls } from '../playback/audio-cache-ui';
import { clearPerReciterState } from './clear-per-reciter-state';
import { _isCurrentReciterBySurah } from './reciter';

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

    const allPromise = fetchJson<SegAllResponse>(`/api/seg/all/${reciter}`)
        .then((all) => {
            if (get(selectedReciter) !== reciter) return;
            if ('error' in all) {
                console.error('Error loading all segments:', (all as any).error);
                return;
            }
            segAllData.set(all);
            reciterVbrChapters.set(new Set(all.reciter_vbr_chapters ?? []));
            _rewriteAudioUrls();
            preconnectOrigins(Object.values(all.audio_by_chapter ?? {}));
            if (_isCurrentReciterBySurah()) void _fetchCacheStatus(reciter);
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
