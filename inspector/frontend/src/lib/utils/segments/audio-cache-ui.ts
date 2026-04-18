import { get } from 'svelte/store';

import { fetchJson } from '../../api';
import {
    cacheDeleteButton,
    cachePrepareButton,
    cacheProgress,
    cacheStatus,
    cacheStatusText,
} from '../../stores/segments/audio-cache';
import { selectedReciter } from '../../stores/segments/chapter';
import type {
    SegAudioCacheStatusResponse,
    SegDeleteAudioCacheResponse,
    SegPrepareAudioResponse,
} from '../../types/api';
import type { TimerHandle } from '../../types/segments';
import { _formatBytes } from '../formatting';

// ---------------------------------------------------------------------------
// Module-local state
// ---------------------------------------------------------------------------

let _audioCachePollTimer: TimerHandle | null = null;

/** Clear the running cache-status polling timer (called on reciter change). */
export function clearAudioCachePollTimer(): void {
    if (_audioCachePollTimer) { clearInterval(_audioCachePollTimer); _audioCachePollTimer = null; }
}

/** Formerly rewrote audio URLs to proxy paths. No-op: raw CDN URLs must be preserved
 *  so that the server's HTTP Range peak computation can reach CDN directly. */
export function _rewriteAudioUrls(): void {}

export function _updateCacheStatusUI(data: SegAudioCacheStatusResponse | null | undefined): void {
    if (!data || (data as { error?: string }).error) {
        cacheStatusText.set('');
        cacheProgress.set(null);
        return;
    }

    const allCached = data.cached_count >= data.total;
    cachePrepareButton.update(b => ({ ...b, hidden: allCached }));
    cacheDeleteButton.update(b => ({ ...b, hidden: data.cached_count === 0 }));

    if (data.downloading && data.download_progress) {
        const dp = data.download_progress;
        const pct = dp.total > 0 ? Math.round(dp.downloaded / dp.total * 100) : 0;
        cacheProgress.set({
            pct,
            text: `Downloading ${dp.downloaded} / ${dp.total} chapters (${_formatBytes(data.cached_bytes)})`,
        });
        cacheStatusText.set('');
        cachePrepareButton.update(b => ({ ...b, hidden: true }));
    } else {
        cacheProgress.set(null);
        if (allCached) {
            cacheStatusText.set(`All cached (${_formatBytes(data.cached_bytes)})`);
        } else {
            cacheStatusText.set('Download audio for faster playback while editing');
        }
    }
}

export async function _fetchCacheStatus(reciter: string): Promise<SegAudioCacheStatusResponse | null> {
    try {
        const data = await fetchJson<SegAudioCacheStatusResponse>(
            `/api/seg/audio-cache-status/${reciter}`,
        );
        cacheStatus.set('idle');
        _updateCacheStatusUI(data);
        return data;
    } catch { return null; }
}

export async function _prepareAudio(reciter: string): Promise<void> {
    cachePrepareButton.update(b => ({ ...b, disabled: true, hidden: true }));
    try {
        await fetchJson<SegPrepareAudioResponse>(`/api/seg/prepare-audio/${reciter}`, {
            method: 'POST',
        });
    } catch { /* poll will handle */ }
    if (_audioCachePollTimer) clearInterval(_audioCachePollTimer);
    _audioCachePollTimer = setInterval(async () => {
        if (get(selectedReciter) !== reciter) {
            if (_audioCachePollTimer) { clearInterval(_audioCachePollTimer); _audioCachePollTimer = null; }
            return;
        }
        const data = await _fetchCacheStatus(reciter);
        if (data && (!data.downloading || data.cached_count >= data.total)) {
            if (_audioCachePollTimer) { clearInterval(_audioCachePollTimer); _audioCachePollTimer = null; }
            cachePrepareButton.update(b => ({ ...b, disabled: false, label: 'Download All Audio' }));
            _updateCacheStatusUI(data);
        }
    }, 2000);
}

export async function _deleteAudioCache(reciter: string): Promise<void> {
    if (!confirm('Delete cached audio for this reciter?\nOnly delete once you are finished editing.')) return;
    cacheDeleteButton.update(b => ({ ...b, disabled: true, label: 'Deleting...' }));
    try {
        await fetchJson<SegDeleteAudioCacheResponse>(`/api/seg/delete-audio-cache/${reciter}`, {
            method: 'DELETE',
        });
    } catch { /* ignore */ }
    cacheDeleteButton.update(b => ({ ...b, disabled: false, label: 'Delete Cache' }));
    await _fetchCacheStatus(reciter);
}
