/**
 * Reset per-reciter imperative state so validation / stats / history /
 * save-preview panels reset when the user switches reciter OR a stale-data
 * reload triggers.
 *
 * Shared between SegmentsTab's reciter handler (direct call) and the
 * stale-data reload path in reciter-actions.ts::reloadCurrentReciter().
 */

import { state } from '../../segments-state';
import { segAllData, segData } from '../../stores/segments/chapter';
import { clearEdit } from '../../stores/segments/edit';
import { setHistoryData, setHistoryVisible } from '../../stores/segments/history';
import { clearSavePreviewData, hidePreview } from '../../stores/segments/save';
import { clearStats } from '../../stores/segments/stats';
import { clearValidation } from '../../stores/segments/validation';
import { clearWaveformCache } from '../waveform-cache';
import { stopSegAnimation } from './playback';

export function clearPerReciterState(): void {
    if (state._waveformObserver) {
        state._waveformObserver.disconnect();
        state._waveformObserver = null;
    }
    segAllData.set(null);
    segData.set(null);
    state.segCurrentIdx = -1;
    state.segDirtyMap.clear();
    state.segOpLog.clear();
    state._pendingOp = null;
    state.segEditMode = null;
    state.segEditIndex = -1;
    clearEdit();

    clearValidation();
    clearStats();

    state._segSavedChains = null;
    const histBtn = document.getElementById('seg-history-btn');
    setHistoryVisible(false);
    setHistoryData(null);
    const savePrev = document.getElementById('seg-save-preview');
    if (histBtn) (histBtn as HTMLElement).hidden = true;
    if (savePrev) (savePrev as HTMLElement).hidden = true;
    hidePreview();
    clearSavePreviewData();

    state._segPrefetchCache = {};
    state._segContinuousPlay = false;
    state._segPlayEndMs = 0;
    clearWaveformCache();
    if (state._peaksPollTimer) { clearTimeout(state._peaksPollTimer); state._peaksPollTimer = null; }
    state._segPeaksByUrl = null;
    state._observerPeaksQueue = [];
    if (state._observerPeaksTimer) { clearTimeout(state._observerPeaksTimer); state._observerPeaksTimer = null; }
    state._observerPeaksRequested = new Set();

    const cacheBar = document.getElementById('seg-cache-bar');
    if (cacheBar) (cacheBar as HTMLElement).hidden = true;
    if (state._audioCachePollTimer) { clearInterval(state._audioCachePollTimer); state._audioCachePollTimer = null; }

    const saveBtn = document.getElementById('seg-save-btn') as HTMLButtonElement | null;
    const playBtn = document.getElementById('seg-play-btn') as HTMLButtonElement | null;
    const playStatus = document.getElementById('seg-play-status');
    if (saveBtn) saveBtn.disabled = true;
    if (playBtn) playBtn.disabled = true;
    if (playStatus) playStatus.textContent = '';

    stopSegAnimation();
}
