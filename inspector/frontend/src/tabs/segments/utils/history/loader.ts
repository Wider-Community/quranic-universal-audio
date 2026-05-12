/**
 * Lazy/background edit-history loader.
 *
 * Reciter selection starts the history fetch without blocking chapter
 * selection. Opening History awaits the same in-flight promise and then loads
 * persisted waveform peaks, which are only useful inside the History view.
 */

import { get } from 'svelte/store';

import { fetchJsonOrNull } from '../../../../lib/api';
import type { SegEditHistoryResponse } from '../../../../lib/types/api';
import { selectedReciter } from '../../stores/chapter';
import {
    historyLoadState,
} from '../../stores/history';
import { indexHistoryPeaksRecords } from '../waveform/utils';
import { renderEditHistoryPanel } from './render';

interface HistoryPeaksResponse {
    records: Array<{
        op_id?: string;
        url?: string;
        start_ms?: number;
        end_ms?: number;
        peaks?: unknown;
        duration_ms?: number;
    }>;
}

let _historyReciter = '';
let _historyPromise: Promise<SegEditHistoryResponse | null> | null = null;
const _peaksLoadedFor = new Set<string>();

function _hasHistory(data: SegEditHistoryResponse | null | undefined): boolean {
    return !!data?.batches?.length;
}

export function resetHistoryLoader(): void {
    _historyReciter = '';
    _historyPromise = null;
    historyLoadState.set('idle');
}

export function startHistoryLoad(reciter: string): Promise<SegEditHistoryResponse | null> {
    if (!reciter) {
        resetHistoryLoader();
        return Promise.resolve(null);
    }
    if (_historyPromise && _historyReciter === reciter) {
        return _historyPromise;
    }

    _historyReciter = reciter;
    historyLoadState.set('loading');
    _historyPromise = fetchJsonOrNull<SegEditHistoryResponse>(
        `/api/seg/edit-history/${reciter}`,
    ).then((data) => {
        if (get(selectedReciter) !== reciter) return data;
        renderEditHistoryPanel(data);
        historyLoadState.set(_hasHistory(data) ? 'loaded' : 'empty');
        return data;
    }).catch((err) => {
        if (get(selectedReciter) === reciter) {
            console.error('Error loading edit history:', err);
            historyLoadState.set('error');
        }
        return null;
    });
    return _historyPromise;
}

export async function ensureHistoryReady(): Promise<void> {
    const reciter = get(selectedReciter);
    if (!reciter) return;
    await startHistoryLoad(reciter);

    if (get(selectedReciter) !== reciter || _peaksLoadedFor.has(reciter)) return;
    const peaks = await fetchJsonOrNull<HistoryPeaksResponse>(
        `/api/seg/history-peaks/${reciter}`,
    );
    if (get(selectedReciter) !== reciter) return;
    if (peaks?.records) indexHistoryPeaksRecords(peaks.records);
    _peaksLoadedFor.add(reciter);
}
