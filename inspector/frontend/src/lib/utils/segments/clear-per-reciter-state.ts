/**
 * Reset per-reciter imperative state so validation / stats / history /
 * save-preview panels reset when the user switches reciter OR a stale-data
 * reload triggers.
 *
 * Shared between SegmentsTab's reciter handler (direct call) and the
 * stale-data reload path in reciter-actions.ts::reloadCurrentReciter().
 */

import { cacheStatus } from '../../stores/segments/audio-cache';
import {
    segAllData,
    segCurrentIdx,
    segData,
} from '../../stores/segments/chapter';
import { setPendingOp } from '../../stores/segments/dirty';
import {
    clearDirtyMap,
    clearOpLog,
} from '../../stores/segments/dirty';
import { clearEdit } from '../../stores/segments/edit';
import { setHistoryData, setHistoryVisible } from '../../stores/segments/history';
import {
    continuousPlay,
    playEndMs,
    playingSegmentIndex,
} from '../../stores/segments/playback';
import {
    clearSavePreviewData,
    hidePreview,
    savedChains,
} from '../../stores/segments/save';
import { clearStats } from '../../stores/segments/stats';
import { clearValidation } from '../../stores/segments/validation';
import { clearWaveformCache } from '../waveform-cache';
import { clearAudioCachePollTimer } from './audio-cache-ui';
import { clearSegPrefetchCache, stopSegAnimation } from './playback';
import { resetWaveformState } from './waveform-utils';

export function clearPerReciterState(): void {
    resetWaveformState();
    segAllData.set(null);
    segData.set(null);
    segCurrentIdx.set(-1);
    clearDirtyMap();
    clearOpLog();
    setPendingOp(null);
    clearEdit();

    clearValidation();
    clearStats();

    savedChains.set(null);
    const histBtn = document.getElementById('seg-history-btn');
    setHistoryVisible(false);
    setHistoryData(null);
    const savePrev = document.getElementById('seg-save-preview');
    if (histBtn) (histBtn as HTMLElement).hidden = true;
    if (savePrev) (savePrev as HTMLElement).hidden = true;
    hidePreview();
    clearSavePreviewData();

    clearSegPrefetchCache();
    continuousPlay.set(false);
    playEndMs.set(0);
    playingSegmentIndex.set(-1);
    clearWaveformCache();

    cacheStatus.set('hidden');
    clearAudioCachePollTimer();

    const saveBtn = document.getElementById('seg-save-btn') as HTMLButtonElement | null;
    const playBtn = document.getElementById('seg-play-btn') as HTMLButtonElement | null;
    const playStatus = document.getElementById('seg-play-status');
    if (saveBtn) saveBtn.disabled = true;
    if (playBtn) playBtn.disabled = true;
    if (playStatus) playStatus.textContent = '';

    stopSegAnimation();
}
