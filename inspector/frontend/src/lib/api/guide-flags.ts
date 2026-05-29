/**
 * Dev-only accordion-guide flagging client.
 *
 * Backed by `POST/GET/DELETE /api/dev/guide-flag(s)`, registered only when the
 * Flask server runs with `INSPECTOR_DEV_MODE=1`. On the deployed HF Space the
 * endpoints 404 and this module is never reached — the UI hides the flag button
 * (gated on `$currentUser.dev_mode`). See `docs/reference/accordion-guides.md`.
 */

import { fetchJson } from '../api';

export type GuideRenderKind = 'history_op' | 'edit_chain';

export interface GuideFlagPayload {
    reciter: string;
    chapter: number | null;
    batch_id: string;
    op_ids: string[];
    op_type?: string | null;
    matched_ref?: string | null;
    /** Which validation category's guide this example belongs under. */
    category: string;
    render?: GuideRenderKind;
    note?: string;
    /** Optional proposed `GuideExample` id (kebab/snake). */
    example_id?: string;
}

export interface GuideFlag extends GuideFlagPayload {
    flag_id: string;
    flagged_at_utc: string;
    flagged_by?: string | null;
}

interface FlagResponse { ok?: boolean; flag?: GuideFlag; error?: string }

/** Queue one flagged edit. Throws on a backend error or 404 (dev-mode off). */
export async function flagGuideExample(payload: GuideFlagPayload): Promise<GuideFlag> {
    const res = await fetchJson<FlagResponse>('/api/dev/guide-flag', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!res?.flag) throw new Error(res?.error || 'guide flag failed');
    return res.flag;
}

/** List all queued flags (oldest-first). Empty when dev mode is off. */
export async function listGuideFlags(): Promise<GuideFlag[]> {
    const res = await fetchJson<{ flags?: GuideFlag[] }>('/api/dev/guide-flags', {
        credentials: 'same-origin',
    });
    return res?.flags ?? [];
}

/** Remove one queued flag by id. Returns true if one was removed. */
export async function deleteGuideFlag(flagId: string): Promise<boolean> {
    const res = await fetchJson<{ ok?: boolean }>(
        `/api/dev/guide-flag/${encodeURIComponent(flagId)}`,
        { method: 'DELETE', credentials: 'same-origin' },
    );
    return !!res?.ok;
}
