<script lang="ts">
    /**
     * RequestForm — dual-mode reciter-request panel.
     *
     * Mode `'create'` (any signed-in user):
     * - Prefilled with the current delivery + reciter metadata
     * - Editable fields (riwayah/style dropdowns, name/year/etc text inputs)
     * - Submit fires `POST /api/reciter/<slug>/request`
     *
     * Mode `'review'` (maintainer + owner):
     * - Read-only display of the existing pending request
     * - Reject Soft + Reject Hard buttons, each prompting for a ≥10-char reason
     * - Owner-only: shows requester actor identity
     *
     * Non-blocking conflict warning when proposed (riwayah, style) collides
     * with another delivery of the same reciter — admin gets full agency.
     */
    import { createEventDispatcher, onMount } from 'svelte';

    import {
        fetchPendingRequest,
        rejectRequestHard,
        rejectRequestSoft,
        submitRequest,
        type PendingRequest,
        type ProposedEdits,
    } from '../../../lib/api/requests';
    import { isOwner } from '../../../lib/stores/current-user';
    import type {
        AdminBucket,
        PublicDelivery,
        PublicReciter,
    } from '../../../lib/types/public-state';
    import {
        COUNTRIES,
        countryByCode,
        normalizeCountry as resolveCountry,
    } from '../../../lib/utils/countries';

    /**
     * Recording-year plausibility bounds. Lower: 1885 (early phonograph era).
     * Upper: current year, computed at component load so the field tolerates
     * year rollovers without redeploy. Mirrors
     * ``scripts/lib/schemas/pending_requests.py::_check_year``.
     */
    const MIN_RECORDING_YEAR = 1885;
    const MAX_RECORDING_YEAR = new Date().getFullYear();

    export let mode: 'create' | 'review';
    export let reciter: PublicReciter;
    export let delivery: PublicDelivery;

    const dispatch = createEventDispatcher<{
        submitted: { slug: string };
        rejected: { slug: string; kind: 'soft' | 'hard' };
        close: void;
    }>();

    let pending: PendingRequest | null = null;
    let pendingError: string | null = null;
    let busy = false;
    let formError: string | null = null;

    // Form fields (used in both modes; review mode renders them disabled).
    let riwayah = delivery.riwayah;
    let style = delivery.style;
    let name_en = reciter.name;
    let name_ar = reciter.name_ar ?? '';
    // Legacy catalog rows store country as the full name (e.g. "Saudi Arabia")
    // instead of the ISO-2 code the schema documents. The resolver accepts
    // either shape and returns the canonical code so the datalist recognises
    // the prefill — catalog migrates naturally to ISO-2 as edits land.
    let country = resolveCountry(reciter.country);
    let recording_context = delivery.recording_context ?? '';
    let recording_year: number | '' = delivery.recording_year ?? '';
    let comments = '';
    let autoClaim = false;

    // Vocab options fetched lazily from /api/static/catalog.json.
    let riwayatOptions: { slug: string; name: string }[] = [];
    let styleOptions: { slug: string; name: string }[] = [];
    let contextOptions: { slug: string; name: string }[] = [];

    onMount(async () => {
        try {
            const resp = await fetch('/api/static/catalog.json');
            if (resp.ok) {
                const cat = await resp.json();
                riwayatOptions = (cat?.vocab?.riwayat ?? []).map(
                    (r: { slug: string; name: string }) => ({ slug: r.slug, name: r.name }),
                );
                styleOptions = (cat?.vocab?.styles ?? []).map(
                    (s: { slug: string; name: string }) => ({ slug: s.slug, name: s.name }),
                );
                contextOptions = (cat?.vocab?.recording_contexts ?? []).map(
                    (c: { slug: string; name: string }) => ({ slug: c.slug, name: c.name }),
                );
            }
        } catch {
            // Vocab fetch is best-effort; if it fails the dropdowns will show
            // raw slug strings of whatever the user typed/selected.
        }

        if (mode === 'review') {
            await loadPending();
        }
    });

    async function loadPending(): Promise<void> {
        try {
            pending = await fetchPendingRequest(delivery.slug);
            if (pending) {
                riwayah = pending.proposed_edits.riwayah ?? riwayah;
                style = pending.proposed_edits.style ?? style;
                name_en = pending.proposed_edits.name_en ?? name_en;
                name_ar = pending.proposed_edits.name_ar ?? name_ar;
                country = resolveCountry(pending.proposed_edits.country ?? country);
                recording_context =
                    pending.proposed_edits.recording_context ?? recording_context;
                recording_year = pending.proposed_edits.recording_year ?? recording_year;
                comments = pending.comments ?? '';
                autoClaim = pending.auto_claim;
            } else {
                pendingError =
                    'No pending request for this combination (it may have been cleared).';
            }
        } catch (e) {
            pendingError = (e as Error).message;
        }
    }

    /**
     * On country-input blur: resolve whatever the user typed (code or
     * full name) to the canonical ISO-2 code. The datalist passes the
     * selected option's value (the code) through directly so most picks
     * land here already normalized; this catches the keyboard-only path
     * where someone types "saudi arabia" without selecting from the list.
     * Unknown strings round-trip unchanged so the user can fix them.
     */
    function normalizeCountry(): void {
        country = resolveCountry(country);
    }

    $: countryMatch = countryByCode(country);
    /** True iff the user typed a country that doesn't match any ISO-2 entry.
     *  Blank is fine (truly unknown is allowed); only a populated-but-invalid
     *  value blocks submission. */
    $: invalidCountry = !!country && !countryMatch;

    /**
     * Compute the proposed_edits patch: only include fields the user
     * actually changed from the prefilled values. Server applies the patch
     * over the existing catalog on auto-acceptance.
     */
    function buildEdits(): ProposedEdits {
        const out: ProposedEdits = {};
        if (riwayah && riwayah !== delivery.riwayah) out.riwayah = riwayah;
        if (style && style !== delivery.style) out.style = style;
        if (name_en && name_en !== reciter.name) out.name_en = name_en;
        if (name_ar !== (reciter.name_ar ?? '')) out.name_ar = name_ar || null;
        // Compare against the normalized form of the catalog value so legacy
        // rows storing full names (e.g. "Saudi Arabia") don't show up as
        // edits when the user hasn't touched the field. On submit we always
        // send the ISO-2 code regardless.
        if (country !== resolveCountry(reciter.country)) {
            out.country = country || null;
        }
        if (recording_context !== (delivery.recording_context ?? '')) {
            out.recording_context = recording_context || null;
        }
        if (
            recording_year !== '' &&
            recording_year !== delivery.recording_year
        ) {
            out.recording_year = Number(recording_year);
        }
        return out;
    }

    /**
     * Non-blocking conflict check: proposed (riwayah, style) matches another
     * delivery of the same reciter. Computed client-side from the reciter
     * detail payload. Doesn't block submission.
     */
    $: conflict =
        mode === 'create' &&
        (riwayah !== delivery.riwayah || style !== delivery.style) &&
        reciter.deliveries.some(
            (d) =>
                d.slug !== delivery.slug
                && d.riwayah === riwayah
                && d.style === style,
        );

    async function onSubmit(): Promise<void> {
        if (busy) return;
        if (invalidCountry) {
            formError = 'Country must be a valid ISO-2 code from the list, or blank.';
            return;
        }
        formError = null;
        busy = true;
        try {
            const edits = buildEdits();
            await submitRequest(
                delivery.slug,
                edits,
                comments.trim() ? comments.trim() : null,
                autoClaim,
            );
            dispatch('submitted', { slug: delivery.slug });
        } catch (e) {
            formError = (e as Error).message;
        } finally {
            busy = false;
        }
    }

    async function onRejectSoft(): Promise<void> {
        await runReject('soft');
    }

    async function onRejectHard(): Promise<void> {
        await runReject('hard');
    }

    async function runReject(kind: 'soft' | 'hard'): Promise<void> {
        if (busy) return;
        const verb = kind === 'soft' ? 'send back' : 'discard';
        const reason = window.prompt(
            `Reason (≥10 chars) for ${verb}ing this request — recorded in the audit log:`,
            '',
        );
        if (reason === null) return;
        const trimmed = reason.trim();
        if (trimmed.length < 10) {
            window.alert('Reason must be at least 10 characters.');
            return;
        }
        formError = null;
        busy = true;
        try {
            if (kind === 'soft') {
                await rejectRequestSoft(delivery.slug, trimmed);
            } else {
                await rejectRequestHard(delivery.slug, trimmed);
            }
            dispatch('rejected', { slug: delivery.slug, kind });
        } catch (e) {
            formError = (e as Error).message;
        } finally {
            busy = false;
        }
    }

    $: readOnly = mode === 'review';
    $: title =
        mode === 'create'
            ? `Request ${reciter.name} (${delivery.riwayah} · ${delivery.style})`
            : `Review request for ${reciter.name}`;
    $: visibleBucket = delivery.bucket as AdminBucket;
</script>

<section class="request-form" aria-label={title}>
    <header>
        <h3>{title}</h3>
        <button class="close" type="button" on:click={() => dispatch('close')}>×</button>
    </header>

    {#if mode === 'create'}
        <div class="intro">
            <p class="intro-heading">Request rules</p>
            <ul class="rules">
                <li>
                    Listen to some quick audio samples and verify the audio
                    belongs to the correct reciter, style, and riwayah —
                    and that quality is decent. Verify accurate metadata for this reciter combination
                    and edit anything that looks wrong.
                </li>
                <li>
                    If multiple combinations of this riwayah / style /
                    context exist, pick the one with the highest coverage,
                    followed by best channel audio quality, followed by highest bitrate.
                    (Different channels may be serving the same
                    recording or a different one — listen to compare.)
                </li>
                <li>
                    An admin will review your submission. State changes to Available for Review / Under Review
                    automatically once the alignment pipeline finishes.
                </li>
            </ul>
        </div>
    {:else if pending && $isOwner}
        <p class="intro">
            Submitted by <strong>@{pending.requester_login}</strong>
            on {new Date(pending.submitted_at).toLocaleString()}.
        </p>
    {:else if pending}
        <p class="intro">
            Submitted on {new Date(pending.submitted_at).toLocaleString()}.
        </p>
    {/if}

    {#if pendingError}
        <p class="error">{pendingError}</p>
    {/if}

    <div class="grid">
        <label>
            <span>Riwayah</span>
            <select bind:value={riwayah} disabled={readOnly}>
                {#each riwayatOptions as r (r.slug)}
                    <option value={r.slug}>{r.name}</option>
                {/each}
                {#if !riwayatOptions.some((r) => r.slug === riwayah)}
                    <option value={riwayah}>{riwayah}</option>
                {/if}
            </select>
        </label>

        <label>
            <span>Style</span>
            <select bind:value={style} disabled={readOnly}>
                {#each styleOptions as s (s.slug)}
                    <option value={s.slug}>{s.name}</option>
                {/each}
                {#if !styleOptions.some((s) => s.slug === style)}
                    <option value={style}>{style}</option>
                {/if}
            </select>
        </label>

        <label>
            <span>English name</span>
            <input type="text" bind:value={name_en} disabled={readOnly} />
        </label>

        <label class="rtl">
            <span>Arabic name</span>
            <input type="text" bind:value={name_ar} dir="rtl" disabled={readOnly} />
        </label>

        <label>
            <span>Country</span>
            <input
                type="text"
                list="request-form-countries"
                bind:value={country}
                placeholder="Type country name or ISO-2 code"
                disabled={readOnly}
                on:blur={normalizeCountry}
            />
            {#if country && countryMatch}
                <span class="field-hint">{countryMatch.name}</span>
            {:else if country}
                <span class="field-hint warn">
                    Not a valid country — pick one from the list or leave blank.
                </span>
            {/if}
        </label>

        <label>
            <span>Recording context</span>
            <select bind:value={recording_context} disabled={readOnly}>
                <option value="">— Leave blank if unsure</option>
                {#each contextOptions as c (c.slug)}
                    <option value={c.slug}>{c.name}</option>
                {/each}
                {#if recording_context && !contextOptions.some((c) => c.slug === recording_context)}
                    <option value={recording_context}>{recording_context}</option>
                {/if}
            </select>
        </label>

        <label>
            <span>Recording year</span>
            <input
                type="number"
                min={MIN_RECORDING_YEAR}
                max={MAX_RECORDING_YEAR}
                placeholder="Leave blank if unsure"
                bind:value={recording_year}
                disabled={readOnly}
            />
            {#if recording_year !== '' && (recording_year < MIN_RECORDING_YEAR || recording_year > MAX_RECORDING_YEAR)}
                <span class="field-hint warn">
                    Year must be between {MIN_RECORDING_YEAR} and {MAX_RECORDING_YEAR}.
                </span>
            {/if}
        </label>
    </div>

    <datalist id="request-form-countries">
        {#each COUNTRIES as c (c.code)}
            <option value={c.code}>{c.name}</option>
        {/each}
    </datalist>

    <label class="comments">
        <span>Comments {mode === 'create' ? '(optional)' : ''}</span>
        <textarea
            bind:value={comments}
            maxlength="1000"
            rows="3"
            placeholder={mode === 'create'
                ? 'Anything the admin should know...'
                : ''}
            disabled={readOnly}
        ></textarea>
    </label>

    <label class="auto-claim">
        <input
            type="checkbox"
            bind:checked={autoClaim}
            disabled={readOnly}
        />
        <span class="auto-claim-text">
            <span class="auto-claim-label">
                Automatically assign me as reviewer to fix errors once
                alignment is complete
            </span>
            <span class="auto-claim-hint">
                If unchecked, another contributor can claim the reviewing.
            </span>
        </span>
    </label>

    {#if conflict}
        <p class="warning">
            Heads up: another delivery of {reciter.name} already uses
            ({riwayah} · {style}). Submission is still allowed — the admin
            will review and decide.
        </p>
    {/if}

    {#if formError}
        <p class="error">{formError}</p>
    {/if}

    <footer>
        <button type="button" class="ghost" on:click={() => dispatch('close')}>
            {mode === 'create' ? 'Cancel' : 'Close'}
        </button>
        {#if mode === 'create'}
            <button
                type="button"
                class="primary"
                on:click={onSubmit}
                disabled={busy || invalidCountry}
                title={invalidCountry ? 'Fix the country field first' : ''}
            >
                {busy ? 'Submitting…' : 'Submit request'}
            </button>
        {:else if pending}
            <div class="admin-actions">
                <button
                    type="button"
                    class="ghost"
                    on:click={onRejectSoft}
                    disabled={busy}
                >
                    Send back
                </button>
                <button
                    type="button"
                    class="danger"
                    on:click={onRejectHard}
                    disabled={busy}
                >
                    Discard
                </button>
            </div>
        {/if}
    </footer>

    <p class="meta">
        Current state: <span class="bucket bucket-{visibleBucket.replace(/_/g, '-')}">
            {visibleBucket.replace(/_/g, ' ')}
        </span>
    </p>
</section>

<style>
    .request-form {
        background: var(--canvas);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        padding: var(--s-5);
        width: min(640px, 92vw);
        display: flex;
        flex-direction: column;
        gap: var(--s-3);
    }
    header {
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    header h3 {
        margin: 0;
        font-size: var(--fs-h3);
        font-weight: 500;
        color: var(--text-primary);
    }
    .close {
        background: transparent;
        border: 0;
        font-size: 18px;
        color: var(--text-muted);
        cursor: pointer;
        line-height: 1;
        padding: 4px 8px;
    }
    .intro {
        margin: 0;
        font-size: var(--fs-meta);
        color: var(--text-muted);
        line-height: var(--lh-normal);
    }
    .intro-heading {
        margin: 0 0 var(--s-1);
        font-weight: 500;
        color: var(--text-secondary);
    }
    .rules {
        margin: 0;
        padding-left: var(--s-4);
        display: flex;
        flex-direction: column;
        gap: var(--s-1);
    }
    .rules li {
        line-height: 1.45;
    }
    .field-hint {
        margin-top: 2px;
        font-size: 10.5px;
        color: var(--text-faint);
    }
    .field-hint.warn {
        color: var(--state-error-fg);
    }
    .grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: var(--s-3);
    }
    label {
        display: flex;
        flex-direction: column;
        gap: 4px;
        font-size: var(--fs-meta);
        color: var(--text-secondary);
    }
    label span {
        color: var(--text-muted);
    }
    label.rtl input { text-align: right; }
    input, select, textarea {
        background: var(--panel);
        border: 1px solid var(--border-default);
        color: var(--text-primary);
        border-radius: var(--r-2);
        padding: 6px 8px;
        font: inherit;
    }
    input:disabled, select:disabled, textarea:disabled {
        opacity: 0.7;
        cursor: not-allowed;
    }
    .comments textarea {
        resize: vertical;
        min-height: 60px;
    }
    .auto-claim {
        display: flex;
        flex-direction: row;
        align-items: flex-start;
        gap: var(--s-2);
        margin-top: var(--s-2);
        padding: var(--s-2) var(--s-3);
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        cursor: pointer;
    }
    .auto-claim input[type='checkbox'] {
        margin-top: 3px;
        flex-shrink: 0;
    }
    .auto-claim-text {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    .auto-claim-label {
        color: var(--text-primary);
        font-size: var(--fs-meta);
    }
    .auto-claim-hint {
        color: var(--text-muted);
        font-size: 10.5px;
        line-height: 1.35;
    }
    .warning {
        margin: 0;
        padding: var(--s-3);
        background: var(--state-requested-bg);
        color: var(--state-requested-fg);
        border-radius: var(--r-2);
        font-size: var(--fs-meta);
    }
    .error {
        margin: 0;
        padding: var(--s-3);
        background: oklch(0.86 0.130 75 / 0.14);
        color: var(--state-error-fg);
        border-radius: var(--r-2);
        font-size: var(--fs-meta);
    }
    footer {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-3);
        margin-top: var(--s-3);
    }
    .admin-actions {
        display: flex;
        gap: var(--s-2);
    }
    button {
        cursor: pointer;
        padding: 6px 12px;
        border-radius: var(--r-2);
        font: inherit;
        border: 1px solid var(--border-default);
        background: var(--panel);
        color: var(--text-primary);
        transition: background var(--t-fast), color var(--t-fast);
    }
    button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    .primary {
        background: var(--state-published-bg);
        color: var(--state-published-fg);
        border-color: var(--state-published-fg);
    }
    .primary:hover:not(:disabled) {
        background: var(--state-published-fg);
        color: var(--canvas);
    }
    .danger {
        color: var(--state-error-fg);
        border-color: var(--state-error-fg);
    }
    .danger:hover:not(:disabled) {
        background: var(--state-error-fg);
        color: var(--canvas);
    }
    .ghost {
        color: var(--text-muted);
    }
    .meta {
        margin: 0;
        font-size: var(--fs-meta);
        color: var(--text-faint);
    }
    .bucket {
        display: inline-block;
        padding: 1px 8px;
        border-radius: 999px;
        font-size: 10.5px;
        margin-left: 4px;
    }
    .bucket-available-for-request {
        color: var(--state-available-request-fg);
        background: var(--state-available-request-bg);
    }
    .bucket-requested {
        color: var(--state-requested-fg);
        background: var(--state-requested-bg);
    }
    .bucket-discarded {
        color: var(--state-discarded-fg);
        background: var(--state-discarded-bg);
    }
</style>
