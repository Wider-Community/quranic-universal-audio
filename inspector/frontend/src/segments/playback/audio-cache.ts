// @ts-nocheck — removed per-file as each module is typed in Phases 4+
/**
 * Audio cache UI -- by_surah proxy cache management.
 */

import { state, dom } from '../state';
import { fetchJson } from '../../shared/api';
import type {
    SegAudioCacheStatusResponse,
    SegDeleteAudioCacheResponse,
    SegPrepareAudioResponse,
} from '../../types/api';

export function _isCurrentReciterBySurah() {
    const reciter = dom.segReciterSelect.value;
    const info = state.segAllReciters.find(r => r.slug === reciter);
    return info && info.audio_source && info.audio_source.startsWith('by_surah');
}

/** Compare a segment's audio_url (may be relative) against segAudioEl.src (always absolute). */
export function _audioSrcMatch(segUrl, elSrc) {
    if (!segUrl || !elSrc) return false;
    if (segUrl === elSrc) return true;
    return elSrc.endsWith(segUrl);
}

/** Rewrite all audio URLs in segAllData to go through the server proxy (by_surah only). */
export function _rewriteAudioUrls() {
    if (!state.segAllData || !_isCurrentReciterBySurah()) return;
    const reciter = dom.segReciterSelect.value;
    const rewrite = url => url && !url.startsWith('/api/') ? `/api/seg/audio-proxy/${reciter}?url=${encodeURIComponent(url)}` : url;
    if (state.segAllData.audio_by_chapter) {
        for (const ch of Object.keys(state.segAllData.audio_by_chapter)) {
            state.segAllData.audio_by_chapter[ch] = rewrite(state.segAllData.audio_by_chapter[ch]);
        }
    }
    if (state.segAllData.segments) {
        state.segAllData.segments.forEach(s => { if (s.audio_url) s.audio_url = rewrite(s.audio_url); });
    }
}

export function _formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
}

export function _updateCacheStatusUI(data) {
    const statusEl = document.getElementById('seg-cache-status');
    const progressEl = document.getElementById('seg-cache-progress');
    const progressFill = document.getElementById('seg-cache-progress-fill');
    const progressText = document.getElementById('seg-cache-progress-text');
    const prepBtn = document.getElementById('seg-prepare-btn');
    const delBtn = document.getElementById('seg-delete-cache-btn');
    if (!statusEl) return;
    if (!data || data.error) {
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

export async function _fetchCacheStatus(reciter) {
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

export async function _prepareAudio(reciter) {
    const prepBtn = document.getElementById('seg-prepare-btn');
    if (prepBtn) { prepBtn.disabled = true; prepBtn.hidden = true; }
    try {
        await fetchJson<SegPrepareAudioResponse>(`/api/seg/prepare-audio/${reciter}`, {
            method: 'POST',
        });
    } catch { /* poll will handle */ }
    if (state._audioCachePollTimer) clearInterval(state._audioCachePollTimer);
    state._audioCachePollTimer = setInterval(async () => {
        if (dom.segReciterSelect.value !== reciter) {
            clearInterval(state._audioCachePollTimer); state._audioCachePollTimer = null; return;
        }
        const data = await _fetchCacheStatus(reciter);
        if (data && (!data.downloading || data.cached_count >= data.total)) {
            clearInterval(state._audioCachePollTimer); state._audioCachePollTimer = null;
            if (prepBtn) { prepBtn.disabled = false; prepBtn.textContent = 'Download All Audio'; }
            _updateCacheStatusUI(data);
        }
    }, 2000);
}

export async function _deleteAudioCache(reciter) {
    if (!confirm('Delete cached audio for this reciter?\nOnly delete once you are finished editing.')) return;
    const delBtn = document.getElementById('seg-delete-cache-btn');
    if (delBtn) { delBtn.disabled = true; delBtn.textContent = 'Deleting...'; }
    try {
        await fetchJson<SegDeleteAudioCacheResponse>(`/api/seg/delete-audio-cache/${reciter}`, {
            method: 'DELETE',
        });
    } catch { /* ignore */ }
    if (delBtn) { delBtn.disabled = false; delBtn.textContent = 'Delete Cache'; }
    await _fetchCacheStatus(reciter);
}
