/**
 * Admin Jobs-tab API client — the unified view over every job kind.
 *
 * - fetchJobs        unified list (running + historical, all kinds), newest-first
 * - fetchJobDetail   one job's full record for the detail drawer
 *
 * Cancel reuses ``cancelReleaseJob`` from ``admin-releases`` (the kind-generic
 * ``/release-jobs/<id>/cancel`` route handles every kind).
 */

import type { JobRecord, JobsListResponse } from '../types/generated/schemas';

export type { JobRecord, JobMember, JobsListResponse } from '../types/generated/schemas';
export { cancelReleaseJob } from './admin-releases';

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

export async function fetchJobs(signal?: AbortSignal): Promise<JobsListResponse> {
    const resp = await fetch('/api/admin/jobs', { signal });
    return _unwrap<JobsListResponse>(resp);
}

export async function fetchJobDetail(
    kind: string,
    jobId: string,
    slug?: string | null,
    signal?: AbortSignal,
): Promise<JobRecord> {
    const params = new URLSearchParams({ kind, job_id: jobId });
    if (slug) params.set('slug', slug);
    const resp = await fetch(`/api/admin/jobs/detail?${params.toString()}`, { signal });
    return _unwrap<JobRecord>(resp);
}
