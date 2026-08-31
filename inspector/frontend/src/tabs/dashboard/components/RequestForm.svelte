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
    import { get } from 'svelte/store';

    import { localeStore, tr } from '../../../lib/i18n/locale-store';
    import { vocabLabel } from '../../../lib/i18n/vocab';
    import * as m from '../../../lib/paraglide/messages';
    import {
        fetchPendingRequest,
        type PendingRequest,
        type ProposedEdits,
        rejectRequestHard,
        rejectRequestSoft,
        submitRequest,
    } from '../../../lib/api/requests';
    import CountryPicker from '../../../lib/components/CountryPicker.svelte';
    import { pushToast } from '../../../lib/stores/toast';
    import { loadCatalogJson } from '../../../lib/resources/catalog';
    import { isOwner } from '../../../lib/stores/current-user';
    import type {
        PublicDelivery,
        PublicReciter,
    } from '../../../lib/types/generated/schemas';
    import { countryName as countryLabel } from '../../../lib/utils/delivery-label';
    import {
        countryByCode,
        countryByName,
        normalizeCountry as resolveCountry,
    } from '../../../lib/utils/countries';

    /**
     * Recording-year plausibility bounds. Lower: 1885 (early phonograph era).
     * Upper: current year, computed at component load so the field tolerates
     * year rollovers without redeploy. Mirrors
     * ``qua_shared/schemas/pending_requests.py::_check_year``.
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
    // The input is bound to the country *name* (e.g. "Saudi Arabia"). The
    // ISO-2 code is shown alongside the field label and stays the canonical
    // wire format. We accept either shape on prefill — legacy catalog rows
    // store the full name, newer rows store the code — and resolve to a
    // canonical name for display. Unresolvable values fall through unchanged
    // so the user can see + fix them.
    let countryName: string = (() => {
        const code = resolveCountry(reciter.country);
        const known = countryByCode(code);
        if (known) return countryLabel(known.code, get(localeStore));
        return reciter.country ?? '';
    })();
    let recording_context = delivery.recording_context ?? '';
    let recording_year: number | '' = delivery.recording_year ?? '';
    let comments = '';
    let autoClaim = false;

    // Vocab options fetched lazily from /api/static/catalog.json.
    let riwayatOptions: { slug: string; short?: string; name: string }[] = [];
    let styleOptions: { slug: string; name: string }[] = [];
    let contextOptions: { slug: string; name: string }[] = [];

    onMount(async () => {
        try {
            const cat = await loadCatalogJson();
            riwayatOptions = (cat?.vocab?.riwayat ?? []).map(
                (r: { slug: string; short?: string; name: string }) => ({ slug: r.slug, short: r.short, name: r.name }),
            );
            styleOptions = (cat?.vocab?.styles ?? []).map(
                (s: { slug: string; name: string }) => ({ slug: s.slug, name: s.name }),
            );
            contextOptions = (cat?.vocab?.recording_contexts ?? []).map(
                (c: { slug: string; name: string }) => ({ slug: c.slug, name: c.name }),
            );
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
                {
                    const incoming = pending.proposed_edits.country;
                    if (incoming != null) {
                        const code = resolveCountry(incoming);
                        const known = countryByCode(code);
                        countryName = known ? countryLabel(known.code, get(localeStore)) : incoming;
                    }
                }
                recording_context =
                    pending.proposed_edits.recording_context ?? recording_context;
                recording_year = pending.proposed_edits.recording_year ?? recording_year;
                comments = pending.comments ?? '';
                autoClaim = pending.auto_claim;
            } else {
                pendingError = m.dashboard_request_pending_cleared();
            }
        } catch (e) {
            pendingError = (e as Error).message;
        }
    }

    /** Resolved ISO-2 code for the currently-typed name. Empty when blank
     *  or unrecognised — the label suffix uses this to render `(SA)` etc. */
    $: countryCode = countryByName(countryName, lang)?.code ?? '';
    /** True iff the user typed a country that doesn't match any ISO-2 entry.
     *  Blank is fine (truly unknown is allowed); only a populated-but-invalid
     *  value blocks submission. */
    $: invalidCountry = !!countryName && !countryCode;

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
        // Wire format is always ISO-2. Compare resolved codes so a legacy
        // full-name catalog value doesn't surface as a phantom edit when the
        // user hasn't touched the field.
        {
            const submittedCode = countryByName(countryName, lang)?.code ?? '';
            const originalCode = resolveCountry(reciter.country);
            if (submittedCode !== originalCode) {
                out.country = submittedCode || null;
            }
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

    // Non-hafs riwayahs aren't aligned yet — non-blocking heads-up. Hafs is
    // matched by vocab SHORT ('hafs'), not the slug ('hafs_an_asim').
    $: selectedRiwayahShort = riwayatOptions.find((r) => r.slug === riwayah)?.short;
    $: nonHafsRiwayah = !!selectedRiwayahShort && selectedRiwayahShort !== 'hafs';

    async function onSubmit(): Promise<void> {
        if (busy) return;
        if (invalidCountry) {
            formError = m.dashboard_request_country_invalid();
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
            pushToast({
                kind: 'success',
                text: m.dashboard_submit_queued_toast(),
                ttl: 9000,
            });
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
        const verb =
            kind === 'soft'
                ? m.dashboard_request_reject_verb_send_back()
                : m.dashboard_request_reject_verb_discard();
        const reason = window.prompt(
            m.dashboard_request_reject_reason_prompt({ verb }),
            '',
        );
        if (reason === null) return;
        const trimmed = reason.trim();
        if (trimmed.length < 10) {
            window.alert(m.dashboard_request_reject_reason_too_short());
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
    $: title = tr(
        $localeStore,
        mode === 'create'
            ? m.dashboard_request_title_create({
                  name: reciter.name,
                  riwayah: vocabLabel('riwayah', delivery.riwayah),
                  style: vocabLabel('style', delivery.style),
              })
            : m.dashboard_request_title_review({ name: reciter.name }),
    );

    // Static chrome labels — bound through `tr($localeStore, …)` so they
    // re-evaluate when the locale switches (legacy Svelte-4 reactivity).
    $: lang = $localeStore;
    $: closeLabel = tr(lang, m.common_action_close());
    $: guidelinesHeading = tr(lang, m.dashboard_request_guidelines_heading());
    $: guidelineVerifyAudio = tr(lang, m.dashboard_request_guideline_verify_audio());
    $: guidelinePickBest = tr(lang, m.dashboard_request_guideline_pick_best());
    $: guidelineReview = tr(lang, m.dashboard_request_guideline_review());
    $: fieldRiwayah = tr(lang, m.dashboard_request_field_riwayah());
    $: fieldStyle = tr(lang, m.dashboard_request_field_style());
    $: fieldEnglishName = tr(lang, m.dashboard_request_field_english_name());
    $: fieldArabicName = tr(lang, m.dashboard_request_field_arabic_name());
    $: fieldCountry = tr(lang, m.dashboard_request_field_country());
    $: countryUnknown = tr(lang, m.dashboard_request_country_unknown());
    $: countryPlaceholder = tr(lang, m.dashboard_request_country_placeholder());
    $: fieldRecordingContext = tr(lang, m.dashboard_request_field_recording_context());
    $: contextBlankOption = tr(lang, m.dashboard_request_context_blank_option());
    $: fieldRecordingYear = tr(lang, m.dashboard_request_field_recording_year());
    $: yearPlaceholder = tr(lang, m.dashboard_request_year_placeholder());
    $: fieldComments = tr(lang, m.dashboard_request_field_comments());
    $: optionalParen = tr(lang, m.common_label_optional_paren());
    $: commentsPlaceholder = tr(lang, m.dashboard_request_comments_placeholder());
    $: autoClaimLabel = tr(lang, m.dashboard_request_auto_claim_label());
    $: autoClaimHintUnchecked = tr(lang, m.dashboard_request_auto_claim_hint_unchecked());
    $: autoClaimHintOneAtATime = tr(lang, m.dashboard_request_auto_claim_hint_one_at_a_time());
    $: nonHafsCallout = tr(lang, m.dashboard_request_non_hafs_callout());
    $: cancelLabel = tr(lang, m.common_action_cancel());
    $: submitInvalidCountryTitle = tr(lang, m.dashboard_request_submit_invalid_country_title());
    $: submittingLabel = tr(lang, m.common_status_submitting());
    $: submitButton = tr(lang, m.dashboard_request_submit_button());
    $: rejectSoftButton = tr(lang, m.dashboard_request_reject_soft_button());
    $: rejectHardButton = tr(lang, m.dashboard_request_reject_hard_button());
</script>

<section class="request-form" aria-label={title}>
    <header>
        <h3>{title}</h3>
        <button
            class="close"
            type="button"
            aria-label={closeLabel}
            on:click={() => dispatch('close')}>×</button>
    </header>

    <div class="body">
    {#if mode === 'create'}
        <div class="intro">
            <p class="intro-heading">{guidelinesHeading}</p>
            <ul class="rules">
                <li>{guidelineVerifyAudio}</li>
                <li>{guidelinePickBest}</li>
                <li>{guidelineReview}</li>
            </ul>
        </div>
    {:else if pending && $isOwner}
        <p class="intro">
            {tr(lang, m.dashboard_request_submitted_by_owner({
                login: pending.requester_login ?? '',
                date: new Date(pending.submitted_at).toLocaleString(),
            }))}
        </p>
    {:else if pending}
        <p class="intro">
            {tr(lang, m.dashboard_request_submitted_on({
                date: new Date(pending.submitted_at).toLocaleString(),
            }))}
        </p>
    {/if}

    {#if pendingError}
        <p class="error">{pendingError}</p>
    {/if}

    <div class="grid">
        <label>
            <span>{fieldRiwayah}</span>
            <select bind:value={riwayah} disabled={readOnly}>
                {#each riwayatOptions as r (r.slug)}
                    <option value={r.slug}>{tr(lang, vocabLabel('riwayah', r.slug))}</option>
                {/each}
                {#if !riwayatOptions.some((r) => r.slug === riwayah)}
                    <option value={riwayah}>{tr(lang, vocabLabel('riwayah', riwayah))}</option>
                {/if}
            </select>
        </label>

        <label>
            <span>{fieldStyle}</span>
            <select bind:value={style} disabled={readOnly}>
                {#each styleOptions as s (s.slug)}
                    <option value={s.slug}>{tr(lang, vocabLabel('style', s.slug))}</option>
                {/each}
                {#if !styleOptions.some((s) => s.slug === style)}
                    <option value={style}>{tr(lang, vocabLabel('style', style))}</option>
                {/if}
            </select>
        </label>

        <label>
            <span>{fieldEnglishName}</span>
            <input type="text" bind:value={name_en} disabled={readOnly} />
        </label>

        <label class="rtl">
            <span>{fieldArabicName}</span>
            <input type="text" bind:value={name_ar} dir="rtl" disabled={readOnly} />
        </label>

        <label>
            <span>
                {fieldCountry}
                {#if countryCode}
                    <span class="label-meta">({countryCode})</span>
                {:else if countryName}
                    <span class="label-meta warn">{countryUnknown}</span>
                {/if}
            </span>
            <CountryPicker
                bind:value={countryName}
                locale={lang}
                placeholder={countryPlaceholder}
                disabled={readOnly}
            />
        </label>

        <label>
            <span>{fieldRecordingContext}</span>
            <select bind:value={recording_context} disabled={readOnly}>
                <option value="">{contextBlankOption}</option>
                {#each contextOptions as c (c.slug)}
                    <option value={c.slug}>{tr(lang, vocabLabel('context', c.slug))}</option>
                {/each}
                {#if recording_context && !contextOptions.some((c) => c.slug === recording_context)}
                    <option value={recording_context}>{tr(lang, vocabLabel('context', recording_context))}</option>
                {/if}
            </select>
        </label>

        <label>
            <span>{fieldRecordingYear}</span>
            <input
                type="number"
                min={MIN_RECORDING_YEAR}
                max={MAX_RECORDING_YEAR}
                placeholder={yearPlaceholder}
                bind:value={recording_year}
                disabled={readOnly}
            />
            {#if recording_year !== '' && (recording_year < MIN_RECORDING_YEAR || recording_year > MAX_RECORDING_YEAR)}
                <span class="field-hint warn">
                    {tr(lang, m.dashboard_request_year_out_of_bounds({
                        min: MIN_RECORDING_YEAR,
                        max: MAX_RECORDING_YEAR,
                    }))}
                </span>
            {/if}
        </label>
    </div>

    <label class="comments">
        <span>{fieldComments} {mode === 'create' ? optionalParen : ''}</span>
        <textarea
            bind:value={comments}
            maxlength="1000"
            rows="3"
            placeholder={mode === 'create' ? commentsPlaceholder : ''}
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
            <span class="auto-claim-label">{autoClaimLabel}</span>
            <span class="auto-claim-hint">{autoClaimHintUnchecked}</span>
            <span class="auto-claim-hint">{autoClaimHintOneAtATime}</span>
        </span>
    </label>

    {#if mode === 'create' && nonHafsRiwayah}
        <p class="callout">{nonHafsCallout}</p>
    {/if}

    {#if conflict}
        <p class="warning">
            {tr(lang, m.dashboard_request_conflict_warning({
                name: reciter.name,
                riwayah: vocabLabel('riwayah', riwayah),
                style: vocabLabel('style', style),
            }))}
        </p>
    {/if}

    {#if formError}
        <p class="error">{formError}</p>
    {/if}
    </div>

    <footer>
        <button type="button" class="ghost" on:click={() => dispatch('close')}>
            {mode === 'create' ? cancelLabel : closeLabel}
        </button>
        {#if mode === 'create'}
            <button
                type="button"
                class="primary"
                on:click={onSubmit}
                disabled={busy || invalidCountry}
                title={invalidCountry ? submitInvalidCountryTitle : ''}
            >
                {busy ? submittingLabel : submitButton}
            </button>
        {:else if pending && $isOwner}
            <div class="admin-actions">
                <button
                    type="button"
                    class="ghost"
                    on:click={onRejectSoft}
                    disabled={busy}
                >
                    {rejectSoftButton}
                </button>
                <button
                    type="button"
                    class="danger"
                    on:click={onRejectHard}
                    disabled={busy}
                >
                    {rejectHardButton}
                </button>
            </div>
        {/if}
    </footer>

</section>

<style>
    .request-form {
        background: var(--canvas);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        padding: var(--s-5);
        width: min(640px, 92vw);
        /* Cap to the viewport minus the backdrop padding (--s-6 each side)
           and the fixed bottom-player height, so the modal never overlaps the
           player or clips off screen. Computed in viewport units rather than
           `100%` — a percentage max-height resolves unreliably against the
           fixed-position backdrop and can be dropped entirely (modal then
           overflows with no scroll). The shell itself doesn't scroll:
           header/footer are pinned by flex and only `.body` scrolls. */
        max-height: min(880px, calc(100vh - 2 * var(--s-6) - var(--player-h, 72px)));
        display: flex;
        flex-direction: column;
        gap: var(--s-3);
        overflow: hidden;
    }
    header {
        flex: none;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    .body {
        flex: 1;
        min-height: 0;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: var(--s-3);
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
        padding-inline-start: var(--s-4);
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
    /* The country field's resolved ISO-2 code (or `(unknown)` when the
       typed value doesn't match any entry) rides alongside the label so
       the input itself stays a plain text box at its natural width. */
    .label-meta {
        margin-inline-start: 4px;
        font-size: 10.5px;
        color: var(--text-faint);
        font-variant-numeric: tabular-nums;
    }
    .label-meta.warn {
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
    label.rtl input { text-align: end; }
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
    .callout {
        margin: 0;
        padding: var(--s-3);
        background: oklch(0.86 0.13 75 / 0.12);
        color: var(--state-error-fg);
        border: 1px solid oklch(0.86 0.13 75 / 0.35);
        border-radius: var(--r-2);
        font-size: var(--fs-meta);
        line-height: var(--lh-normal);
    }
    footer {
        flex: none;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-3);
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
</style>
