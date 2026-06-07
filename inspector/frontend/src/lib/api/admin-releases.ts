/**
 * Admin Releases-tab API client (v2 dataset/release tracks).
 *
 * - fetchReleasesStatus    per-recitation status grid (TS / HF / GH badges)
 * - fetchReleasePreview    dry-run diff + auto-version + CHANGELOG preview
 * - publishHfBatch         launch ONE job publishing a batch of slugs
 * - cancelReleaseJob       cancel an in-flight release job by id
 * - regenerateTs           re-run MFA alignment for a published slug
 * - cutRelease             launch the global GH release cut job
 *
 */

import type {
    AdminCutReleaseRequest,
    AdminGhReleaseMember,
    AdminInFlightJob,
    AdminLastBatch,
    AdminLatestGhRelease,
    AdminLaunchResponse,
    AdminPublishError,
    AdminReleasePreviewResponse,
    AdminReleasePreviewRow,
    AdminReleaseRow,
    AdminReleaseStatusRow,
    AdminReleasesStatusResponse,
    AdminReleasesSummary,
} from '../types/generated/schemas';

export type ReleaseRow = AdminReleaseRow;
export type GhReleaseMember = AdminGhReleaseMember;
export type ReleaseStatusRow = AdminReleaseStatusRow;
export type LatestGhRelease = AdminLatestGhRelease;
export type ReleasesSummary = AdminReleasesSummary;
export type InFlightJob = AdminInFlightJob;
export type LastBatch = AdminLastBatch;
export type PublishError = AdminPublishError;
export type ReleasesStatusResponse = AdminReleasesStatusResponse;
export type ReleasePreviewRow = AdminReleasePreviewRow;
export type ReleasePreviewResponse = AdminReleasePreviewResponse;
export type LaunchResponse = AdminLaunchResponse;
export type CutReleaseBody = AdminCutReleaseRequest;

async function _unwrap<T>(resp: Response): Promise<T> {
    if (resp.ok) return (await resp.json()) as T;
    let msg = `HTTP ${resp.status}`;
    try {
        const body = (await resp.json()) as { error?: string };
        if (body?.error) msg = body.error;
    } catch {
        /* non-JSON body — keep status fallback */
    }
    throw new Error(msg);
}

export async function fetchReleasesStatus(signal?: AbortSignal): Promise<ReleasesStatusResponse> {
    const resp = await fetch('/api/admin/releases/status', { signal });
    return _unwrap<ReleasesStatusResponse>(resp);
}

export async function fetchReleasePreview(signal?: AbortSignal): Promise<ReleasePreviewResponse> {
    const resp = await fetch('/api/admin/release-preview', { signal });
    return _unwrap<ReleasePreviewResponse>(resp);
}

/** Launch ONE HF Job that publishes a batch of slugs. A single slug is just a
 *  batch of one. Returns the launched job id; throws the server error verbatim
 *  (e.g. the 409 "a cut_release is in flight" / "a job is already running"). */
export async function publishHfBatch(slugs: string[]): Promise<LaunchResponse> {
    const resp = await fetch('/api/admin/publish-hf-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slugs }),
    });
    return _unwrap<LaunchResponse>(resp);
}

/** Cancel an in-flight release job (publish / batch / cut / timestamps) by id.
 *  Hard-kills the HF Job container; the next status poll drops the row. */
export async function cancelReleaseJob(jobId: string): Promise<{ job_id: string; canceled: boolean }> {
    const resp = await fetch(
        `/api/admin/release-jobs/${encodeURIComponent(jobId)}/cancel`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' } },
    );
    return _unwrap<{ job_id: string; canceled: boolean }>(resp);
}

/** Launch an MFA timestamps-regeneration job for an already-released slug.
 *  POSTs to the existing generate-timestamps route (no change). On success the
 *  reciter stays released but its HF/GH releases are stamped stale, moving the
 *  row to "Stale on HF" so the operator re-publishes. Throws the server error
 *  verbatim (e.g. the 409 "a timestamps job is already running"). */
export async function regenerateTs(slug: string): Promise<LaunchResponse> {
    const resp = await fetch(
        `/api/admin/generate-timestamps/${encodeURIComponent(slug)}`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' } },
    );
    return _unwrap<LaunchResponse>(resp);
}

/** Launch the global GH cut job. Owner-only via ``release.cut_gh``.
 *  ``expected_version_at_preview`` carries the version the preview computed;
 *  the server 409s if it drifted (forces a re-preview). */
export async function cutRelease(body: CutReleaseBody): Promise<LaunchResponse> {
    const resp = await fetch('/api/admin/cut-release', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    return _unwrap<LaunchResponse>(resp);
}
