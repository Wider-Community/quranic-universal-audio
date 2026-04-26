/**
 * Reciter-level reload action — shared by SegmentsTab's reciter-change
 * handler and the stale-data reload paths in history/save.
 *
 * Fetches chapters + validate + stats + all + edit-history in parallel and
 * mirrors the responses to Svelte stores. Chapter-select options come from
 * `segAllData` reactively.
 */

import { get } from 'svelte/store';

import { fetchJson, fetchJsonOrNull } from '../../../../lib/api';
import { preconnectOrigins } from '../../../../lib/utils/preconnect';
import type {
    SegAllResponse,
    SegChaptersResponse,
    SegEditHistoryResponse,
    SegStatsResponse,
    SegValidateResponse,
} from '../../../../lib/types/api';
import {
    segAllData,
    selectedChapter,
    selectedReciter,
    selectedVerse,
} from '../../stores/chapter';
import { activeFilters } from '../../stores/filters';
import { savedFilterView } from '../../stores/navigation';
import { setStats } from '../../stores/stats';
import { setValidation } from '../../stores/validation';
import { renderEditHistoryPanel } from '../history/render';
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

    // Fetch chapters + validate + stats + all + history in parallel.
    const [chResult, valResult, statsResult, allResult, histResult] = await Promise.allSettled([
        fetchJson<SegChaptersResponse>(`/api/seg/chapters/${reciter}`),
        fetchJson<SegValidateResponse>(`/api/seg/validate/${reciter}`),
        fetchJson<SegStatsResponse>(`/api/seg/stats/${reciter}`),
        fetchJson<SegAllResponse>(`/api/seg/all/${reciter}`),
        fetchJsonOrNull<SegEditHistoryResponse>(`/api/seg/edit-history/${reciter}`),
    ]);

    if (get(selectedReciter) !== reciter) return;
    void chResult; // chapters come from segAllData in Svelte; API response kept to preserve fetch parity

    if (valResult.status === 'fulfilled') {
        setValidation(valResult.value);
    } else {
        console.error('Error loading validation:', valResult.reason);
    }

    if (statsResult.status === 'fulfilled') {
        if (!statsResult.value.error) setStats(statsResult.value);
    } else {
        console.error('Error loading stats:', statsResult.reason);
    }

    if (allResult.status === 'fulfilled') {
        segAllData.set(allResult.value);
        _rewriteAudioUrls();
        preconnectOrigins(Object.values(allResult.value.audio_by_chapter ?? {}));
        if (_isCurrentReciterBySurah()) _fetchCacheStatus(reciter);
    } else {
        console.error('Error loading all segments:', allResult.reason);
    }

    if (histResult.status === 'fulfilled' && histResult.value) {
        renderEditHistoryPanel(histResult.value);
    }
}
