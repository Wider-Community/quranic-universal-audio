/**
 * `/api/samples` client — maintainer alignment samples.
 *
 * Upload is multipart (audio + aligner JSON), so it bypasses `fetchJson`'s
 * JSON assumptions and reads the error envelope itself. Export and audio
 * download are plain navigations to attachment responses.
 */

import type {
    SampleRealignRequest,
    SampleRealignResponse,
    SampleRenameRequest,
    SampleReviewRequest,
    SampleRow,
    SamplesListResponse,
    SegWordTiming,
} from '../types/generated/schemas';
import { fetchJson } from './index';

export class SampleApiError extends Error {
    readonly status: number;
    constructor(status: number, message: string) {
        super(message);
        this.name = 'SampleApiError';
        this.status = status;
    }
}

async function _errorOf(res: Response): Promise<SampleApiError> {
    let message = `Request failed (${res.status})`;
    try {
        const body = (await res.json()) as { error?: string };
        if (body?.error) message = body.error;
    } catch {
        /* non-JSON body — keep the status message */
    }
    return new SampleApiError(res.status, message);
}

export async function listSamples(): Promise<SampleRow[]> {
    const body = await fetchJson<SamplesListResponse & { error?: string }>('/api/samples');
    if (body.error || !Array.isArray(body.samples)) return [];
    return body.samples;
}

/** Mark the sample reviewed (or clear the sign-off). Any later segment save
 *  clears it again server-side. */
export async function reviewSample(id: string, reviewed: boolean): Promise<SampleRow> {
    const body: SampleReviewRequest = { reviewed };
    const res = await fetch(`/api/samples/${encodeURIComponent(id)}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!res.ok) throw await _errorOf(res);
    return (await res.json()) as SampleRow;
}

/** Fresh word timings for one segment span (as the editor holds it) from the
 *  timing Space, audio-absolute ms. The caller commits them via the
 *  `setWordTimings` command. */
export async function realignSampleSegment(id: string, body: SampleRealignRequest): Promise<SegWordTiming[]> {
    const res = await fetch(`/api/samples/${encodeURIComponent(id)}/realign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!res.ok) throw await _errorOf(res);
    return ((await res.json()) as SampleRealignResponse).word_timings;
}

export async function uploadSample(name: string, audio: File, source: File): Promise<SampleRow> {
    const form = new FormData();
    form.set('name', name);
    form.set('audio', audio, audio.name);
    form.set('source', source, source.name);
    const res = await fetch('/api/samples', { method: 'POST', body: form, credentials: 'same-origin' });
    if (!res.ok) throw await _errorOf(res);
    return (await res.json()) as SampleRow;
}

export async function renameSample(id: string, name: string): Promise<SampleRow> {
    const body: SampleRenameRequest = { name };
    const res = await fetch(`/api/samples/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        credentials: 'same-origin',
    });
    if (!res.ok) throw await _errorOf(res);
    return (await res.json()) as SampleRow;
}

export async function deleteSample(id: string): Promise<void> {
    const res = await fetch(`/api/samples/${encodeURIComponent(id)}`, {
        method: 'DELETE',
        credentials: 'same-origin',
    });
    if (!res.ok) throw await _errorOf(res);
}

/** Trigger a browser download of an attachment URL (same pattern as the
 *  dashboard player's surah download). */
function _download(href: string, filename: string): void {
    const a = document.createElement('a');
    a.href = href;
    a.download = filename;
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
}

export function downloadSampleExport(sample: SampleRow): void {
    _download(`/api/samples/${encodeURIComponent(sample.id)}/export`, `${sample.name}.alignment.json`);
}

/** The sample's MP3 through the audio proxy — the same `download=1` route the
 *  dashboard footer player uses for a surah. */
export function downloadSampleAudio(sample: SampleRow): void {
    const url = `qua-sample://${sample.id}/${sample.pseudo_chapter}`;
    const href =
        `/api/seg/audio-proxy/${encodeURIComponent(sample.slug)}`
        + `?url=${encodeURIComponent(url)}&download=1&chapter=${sample.pseudo_chapter}`;
    _download(href, `${sample.name}.mp3`);
}
