/**
 * Reset per-reciter imperative state so validation / stats / history /
 * save-preview panels reset when the user switches reciter OR a stale-data
 * reload triggers.
 *
 * Shared between SegmentsTab's reciter handler (direct call) and the
 * stale-data reload path in reciter-actions.ts::reloadCurrentReciter().
 */

import { clearWaveformCache } from '../../../../lib/utils/waveform-cache';
import { cacheStatus } from '../../stores/audio-cache';
import {
    segAllData,
    segCurrentIdx,
    segData,
} from '../../stores/chapter';
import { setPendingOp } from '../../stores/dirty';
import {
    clearDirtyMap,
    clearOpLog,
} from '../../stores/dirty';
import { clearEdit } from '../../stores/edit';
import { setHistoryData, setHistoryVisible } from '../../stores/history';
import {
    continuousPlay,
    playEndMs,
    playingSegmentIndex,
    playStatusText,
} from '../../stores/playback';
import {
    clearSavePreviewData,
    hidePreview,
    savedChains,
} from '../../stores/save';
import { clearStats } from '../../stores/stats';
import { clearValidation } from '../../stores/validation';
import { clearAudioCachePollTimer } from '../playback/audio-cache-ui';
import { clearSegPrefetchCache, stopSegAnimation } from '../playback/playback';
import { resetWaveformState } from '../waveform/utils';

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
    setHistoryVisible(false);
    setHistoryData(null);
    hidePreview();
    clearSavePreviewData();

    clearSegPrefetchCache();
    continuousPlay.set(false);
    playEndMs.set(0);
    playingSegmentIndex.set(-1);
    clearWaveformCache();

    cacheStatus.set('hidden');
    clearAudioCachePollTimer();

    playStatusText.set('');

    stopSegAnimation();
}
