import { get } from 'svelte/store';

import type {
    SegAudioCacheStatusResponse,
    SegDeleteAudioCacheResponse,
    SegPrepareAudioResponse,
} from '../../../types/api';
import { fetchJson } from '../../api';
import { selectedReciter } from '../../stores/segments/chapter';
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
    const statusEl = document.getElementById('seg-cache-status');
    const progressEl = document.getElementById('seg-cache-progress');
    const progressFill = document.getElementById('seg-cache-progress-fill');
    const progressText = document.getElementById('seg-cache-progress-text');
    const prepBtn = document.getElementById('seg-prepare-btn') as HTMLButtonElement | null;
    const delBtn = document.getElementById('seg-delete-cache-btn') as HTMLButtonElement | null;
    if (!statusEl) return;
    if (!data || (data as { error?: string }).error) {
        statusEl.textContent = '';
        if (progressEl) progressEl.hidden = true;
        return;
    }

    const allCached = data.cached_count >= data.total;
    if (prepBtn) prepBtn.hidden = allCached;
    if (delBtn) delBtn.hidden = data.cached_count === 0;

    if (data.downloading && data.download_progress) {
        const dp = data.download_progress;
        const pct = dp.total > 0 ? Math.round(dp.downloaded / dp.total * 100) : 0;
        if (progressEl) progressEl.hidden = false;
        if (progressFill) progressFill.style.width = pct + '%';
        if (progressText) progressText.textContent = `Downloading ${dp.downloaded} / ${dp.total} chapters (${_formatBytes(data.cached_bytes)})`;
        statusEl.textContent = '';
        if (prepBtn) prepBtn.hidden = true;
    } else {
        if (progressEl) progressEl.hidden = true;
        if (allCached) {
            statusEl.textContent = `All cached (${_formatBytes(data.cached_bytes)})`;
        } else {
            statusEl.textContent = 'Download audio for faster playback while editing';
        }
    }
}

export async function _fetchCacheStatus(reciter: string): Promise<SegAudioCacheStatusResponse | null> {
    try {
        const data = await fetchJson<SegAudioCacheStatusResponse>(
            `/api/seg/audio-cache-status/${reciter}`,
        );
        const bar = document.getElementById('seg-cache-bar');
        if (bar) bar.hidden = false;
        _updateCacheStatusUI(data);
        return data;
    } catch { return null; }
}

export async function _prepareAudio(reciter: string): Promise<void> {
    const prepBtn = document.getElementById('seg-prepare-btn') as HTMLButtonElement | null;
    if (prepBtn) { prepBtn.disabled = true; prepBtn.hidden = true; }
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
            if (prepBtn) { prepBtn.disabled = false; prepBtn.textContent = 'Download All Audio'; }
            _updateCacheStatusUI(data);
        }
    }, 2000);
}

export async function _deleteAudioCache(reciter: string): Promise<void> {
    if (!confirm('Delete cached audio for this reciter?\nOnly delete once you are finished editing.')) return;
    const delBtn = document.getElementById('seg-delete-cache-btn') as HTMLButtonElement | null;
    if (delBtn) { delBtn.disabled = true; delBtn.textContent = 'Deleting...'; }
    try {
        await fetchJson<SegDeleteAudioCacheResponse>(`/api/seg/delete-audio-cache/${reciter}`, {
            method: 'DELETE',
        });
    } catch { /* ignore */ }
    if (delBtn) { delBtn.disabled = false; delBtn.textContent = 'Delete Cache'; }
    await _fetchCacheStatus(reciter);
}
