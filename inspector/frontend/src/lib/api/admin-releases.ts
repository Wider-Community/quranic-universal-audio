/**
 * Admin Releases-tab API client (v2 dataset/release tracks).
 *
 * - fetchReleasesStatus    per-recitation status grid (TS / HF / GH badges)
 * - fetchReleasePreview    dry-run diff + auto-version + CHANGELOG preview
 * - publishHf              launch HF dataset publish for a slug
 * - cutRelease             launch the global GH release cut job
 *
 * Types are defined inline here until the response schemas are promoted to
 * ``qua_shared/schemas/`` + codegen'd. The shapes mirror the Pydantic-free
 * jsonify payloads emitted by ``inspector/routes/admin/releases.py``.
 */

export interface ReleaseRow {
    /** Plan §per_recitation_releases: version is text — job_id for ts,
     * HF commit sha for hf. */
    version: string;
    produced_at: string;
    /** Set on the HF row when a subsequent TS regen invalidates the parquet,
     * or on a GH membership when the slug's TS regenerates after the cut.
     * Cleared by re-publishing. */
    stale_since?: string | null;
}

export interface GhReleaseMember {
    change_kind: 'added' | 'refresh' | 'unchanged';
    stale_since?: string | null;
    release_id?: number;
    ts_version?: string;
}

export interface ReleaseStatusRow {
    slug: string;
    name_en: string | null;
    /** Arabic display name — surfaces in RTL on the row identity line. */
    name_ar: string | null;
    /** Lifecycle state from ``delivery_states`` (``awaiting_review`` /
     *  ``under_review`` / ``released`` / ``awaiting_alignment``) or ``null``
     *  when the slug hasn't entered the state machine yet. Drives the
     *  "Waiting to publish" predicate (released + no HF row + has TS). */
    state: string | null;
    riwayah: string;
    style: string;
    channel: string;
    gh_release_eligible: boolean;
    ts: ReleaseRow | null;
    hf: ReleaseRow | null;
    gh: GhReleaseMember | null;
}

export interface LatestGhRelease {
    version: string;
    produced_at: string;
    external_uri?: string | null;
}

export interface ReleasesSummary {
    version: string | null;
    produced_at: string | null;
    external_uri: string | null;
    member_count: number;
    total_bytes: number;
    days_since_cut: number | null;
}

/** A live HF Job — ``slug`` is null for the global ``cut_release`` kind.
 *  ``timestamps`` is the in-container MFA job (first publish OR regen); it
 *  surfaces here so a regen on a released row shows in the "In progress"
 *  bucket (it has no other in-flight signal — there's no state change). */
export interface InFlightJob {
    kind: 'hf_publish' | 'cut_release' | 'timestamps';
    slug: string | null;
    job_id: string;
    started_at: string | null;
}

export interface ReleasesStatusResponse {
    latest_gh_release: LatestGhRelease | null;
    summary: ReleasesSummary | null;
    in_flight: InFlightJob[];
    recitations: ReleaseStatusRow[];
}

export interface ReleasePreviewRow {
    slug: string;
    name_en: string | null;
    /** Arabic display name — shown trailing the Latin name in the member table. */
    name_ar: string | null;
    /** Display names from the vocab tables (NOT slugs). */
    riwayah: string;
    style: string;
    channel: string;
    /** Surah coverage (chapter_count). Exact ayah coverage is only known at cut
     *  time, so the preview shows surahs. */
    coverage_surahs: number | null;
    change_kind: 'added' | 'refresh' | 'unchanged';
    ts_version: string;
}

export interface ReleasePreviewResponse {
    /** ``null`` when nothing changed since the previous release — operator
     * must supply an explicit ``version`` to force a cut. */
    computed_version: string | null;
    needs_manual_version: boolean;
    previous_version: string | null;
    change_counts: {
        added: number;
        refresh: number;
        unchanged: number;
    };
    added: ReleasePreviewRow[];
    refreshed: ReleasePreviewRow[];
    /** Pre-formatted release date (YYYY-MM-DD) shown in the title line. */
    release_date: string;
    license: string;
    links: { repo: string; hf_dataset: string };
    /** The full release body from the shared renderer — kept for parity/debug;
     *  the modal renders natively from the structured fields above. */
    changelog_preview_md: string;
    /** Echoed back on confirm so the route can 409 a stale preview. */
    expected_version_at_preview: string | null;
}

export interface LaunchResponse {
    job_id: string;
    url: string | null;
}

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

/** Launch the HF dataset publish job for a slug. Returns the launched job
 *  id; throws the server error verbatim (e.g. the 409 "a cut_release is in
 *  flight"). */
export async function publishHf(slug: string): Promise<LaunchResponse> {
    const resp = await fetch(
        `/api/admin/publish-hf/${encodeURIComponent(slug)}`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' } },
    );
    return _unwrap<LaunchResponse>(resp);
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

export interface CutReleaseBody {
    version?: string;
    operator_note?: string;
    expected_version_at_preview?: string | null;
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
