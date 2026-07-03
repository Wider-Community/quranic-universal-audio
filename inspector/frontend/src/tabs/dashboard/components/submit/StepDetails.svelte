<script lang="ts">
    /**
     * Wizard step 3 — combination metadata + comments.
     *
     * Mirrors the per-delivery RequestForm vocab (riwayah / style /
     * recording_context dropdowns + recording_year + comments + auto-claim
     * checkbox) so the contributor surface stays consistent. Vocab is
     * fetched lazily; falling back to whatever raw slug the user typed
     * keeps a bad fetch from blocking the wizard.
     */
    import { onMount } from 'svelte';
    import { fade } from 'svelte/transition';

    import { localeStore, tr } from '$lib/i18n/locale-store';
    import { vocabLabel } from '$lib/i18n/vocab';
    import * as m from '$lib/paraglide/messages';
    import { loadCatalogJson } from '../../../../lib/resources/catalog';
    import { catalogData } from '../../stores/catalog-data';
    import { submitWizard } from '../../stores/submit-wizard';

    const MIN_YEAR = 1885;
    const MAX_YEAR = new Date().getFullYear();

    $: pickedReciter = $submitWizard.existingReciterSlug
        ? $catalogData.reciters.find((r) => r.reciter_id === $submitWizard.existingReciterSlug) ?? null
        : null;

    // Non-blocking conflict: existing reciter already covers (riwayah, style).
    // Mirrors RequestForm.svelte's predicate so the contributor surface stays
    // consistent. Doesn't block submission — admin makes the call.
    $: conflict = !!pickedReciter
        && !!$submitWizard.combination.riwayah
        && !!$submitWizard.combination.style
        && pickedReciter.deliveries.some(
            (d) =>
                d.riwayah === $submitWizard.combination.riwayah
                && d.style === $submitWizard.combination.style,
        );

    // Hafs is identified by its vocab SHORT ('hafs'), not the slug
    // ('hafs_an_asim'). Show the callout only once we know the short and it
    // isn't hafs — avoids a false positive before vocab loads.
    $: selectedRiwayahShort = riwayatOptions.find(
        (r) => r.slug === $submitWizard.combination.riwayah,
    )?.short;
    $: nonHafsRiwayah = !!selectedRiwayahShort && selectedRiwayahShort !== 'hafs';

    $: yearOutOfBounds = $submitWizard.combination.recording_year !== ''
        && (($submitWizard.combination.recording_year as number) < MIN_YEAR
            || ($submitWizard.combination.recording_year as number) > MAX_YEAR);

    interface VocabRow { slug: string; short?: string; name: string; }

    let riwayatOptions: VocabRow[] = [];
    let styleOptions: VocabRow[] = [];
    let contextOptions: VocabRow[] = [];

    $: state = $submitWizard;

    $: lang = $localeStore;
    $: lede = tr(lang, m.dashboard_submit_details_lede());
    $: riwayahLabel = tr(lang, m.dashboard_request_field_riwayah());
    $: pickOne = tr(lang, m.dashboard_submit_pick_one_option());
    $: styleLabel = tr(lang, m.dashboard_request_field_style());
    $: contextLabel = tr(lang, m.dashboard_request_field_recording_context());
    $: optionalLabel = tr(lang, m.common_label_optional());
    $: contextBlank = tr(lang, m.dashboard_submit_context_blank_option());
    $: yearLabel = tr(lang, m.dashboard_request_field_recording_year());
    $: yearPlaceholder = tr(lang, m.dashboard_submit_year_placeholder_dash());
    $: yearBoundsMsg = tr(lang, m.dashboard_request_year_out_of_bounds({ min: MIN_YEAR, max: MAX_YEAR }));
    $: nonHafsCallout = tr(lang, m.dashboard_request_non_hafs_callout());
    $: commentsLabel = tr(lang, m.dashboard_request_field_comments());
    $: commentsPlaceholder = tr(lang, m.dashboard_submit_comments_placeholder());
    $: autoClaimLabel = tr(lang, m.dashboard_submit_auto_claim_label());
    $: autoClaimHint = tr(lang, m.dashboard_submit_auto_claim_hint());
    $: conflictWarning = tr(
        lang,
        m.dashboard_submit_details_conflict_warning({
            name: pickedReciter?.name ?? '',
            riwayah: vocabLabel('riwayah', state.combination.riwayah),
            style: vocabLabel('style', state.combination.style),
        }),
    );

    onMount(async () => {
        try {
            const cat = await loadCatalogJson();
            riwayatOptions = (cat?.vocab?.riwayat ?? []).map((r: VocabRow) => ({ slug: r.slug, short: r.short, name: r.name }));
            styleOptions = (cat?.vocab?.styles ?? []).map((s: VocabRow) => ({ slug: s.slug, name: s.name }));
            contextOptions = (cat?.vocab?.recording_contexts ?? []).map((c: VocabRow) => ({ slug: c.slug, name: c.name }));
        } catch {
            // Best-effort; raw slugs render fine.
        }
    });

    function update<K extends keyof typeof state.combination>(key: K, value: typeof state.combination[K]): void {
        submitWizard.update((s) => ({ ...s, combination: { ...s.combination, [key]: value } }));
    }

    function onYear(e: Event): void {
        const raw = (e.currentTarget as HTMLInputElement).value;
        update('recording_year', raw === '' ? '' : Number(raw));
    }
</script>

<div class="step" in:fade={{ duration: 180 }}>
    <p class="lede">{lede}</p>

    <div class="grid">
        <label>
            <span>{riwayahLabel}</span>
            <select
                value={state.combination.riwayah}
                on:change={(e) => update('riwayah', (e.currentTarget as HTMLSelectElement).value)}
            >
                <option value="" disabled>{pickOne}</option>
                {#each riwayatOptions as r (r.slug)}
                    <option value={r.slug}>{tr(lang, vocabLabel('riwayah', r.slug))}</option>
                {/each}
            </select>
        </label>

        <label>
            <span>{styleLabel}</span>
            <select
                value={state.combination.style}
                on:change={(e) => update('style', (e.currentTarget as HTMLSelectElement).value)}
            >
                <option value="" disabled>{pickOne}</option>
                {#each styleOptions as s (s.slug)}
                    <option value={s.slug}>{tr(lang, vocabLabel('style', s.slug))}</option>
                {/each}
            </select>
        </label>

        <label>
            <span>{contextLabel} <span class="hint">{optionalLabel}</span></span>
            <select
                value={state.combination.recording_context}
                on:change={(e) => update('recording_context', (e.currentTarget as HTMLSelectElement).value)}
            >
                <option value="">{contextBlank}</option>
                {#each contextOptions as c (c.slug)}
                    <option value={c.slug}>{tr(lang, vocabLabel('context', c.slug))}</option>
                {/each}
            </select>
        </label>

        <label>
            <span>{yearLabel} <span class="hint">{optionalLabel}</span></span>
            <input
                type="number"
                min={MIN_YEAR}
                max={MAX_YEAR}
                placeholder={yearPlaceholder}
                value={state.combination.recording_year === '' ? '' : String(state.combination.recording_year)}
                on:input={onYear}
            />
            {#if yearOutOfBounds}
                <span class="field-hint warn">
                    {yearBoundsMsg}
                </span>
            {/if}
        </label>
    </div>

    {#if nonHafsRiwayah}
        <p class="callout" transition:fade={{ duration: 160 }}>
            {nonHafsCallout}
        </p>
    {/if}

    {#if conflict}
        <p class="warning" transition:fade={{ duration: 160 }}>
            {conflictWarning}
        </p>
    {/if}

    <label class="comments">
        <span>{commentsLabel} <span class="hint">{optionalLabel}</span></span>
        <textarea
            rows="3"
            maxlength="1000"
            placeholder={commentsPlaceholder}
            value={state.comments}
            on:input={(e) => submitWizard.update((s) => ({ ...s, comments: (e.currentTarget as HTMLTextAreaElement).value }))}
        ></textarea>
    </label>

    <label class="auto-claim">
        <input
            type="checkbox"
            checked={state.autoClaim}
            on:change={(e) => submitWizard.update((s) => ({ ...s, autoClaim: (e.currentTarget as HTMLInputElement).checked }))}
        />
        <span class="ac-text">
            <span class="ac-label">{autoClaimLabel}</span>
            <span class="ac-hint">{autoClaimHint}</span>
        </span>
    </label>
</div>

<style>
    .step {
        display: flex;
        flex-direction: column;
        gap: var(--s-4);
    }
    .lede {
        margin: 0;
        font-size: var(--fs-meta);
        color: var(--text-muted);
        max-width: 60ch;
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
        color: var(--text-muted);
    }
    .hint {
        color: var(--text-faint);
        margin-inline-start: 6px;
        text-transform: lowercase;
        font-size: 10.5px;
    }
    select, input, textarea {
        background: var(--panel);
        border: 1px solid var(--border-default);
        color: var(--text-primary);
        border-radius: var(--r-2);
        padding: 8px 10px;
        font: inherit;
        transition: border-color var(--t-fast), background var(--t-fast);
    }
    select:focus, input:focus, textarea:focus {
        outline: none;
        border-color: var(--accent);
        background: var(--panel-2);
    }
    .comments textarea {
        resize: vertical;
        min-height: 72px;
    }
    .auto-claim {
        display: flex;
        flex-direction: row;
        align-items: flex-start;
        gap: var(--s-2);
        padding: var(--s-3);
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        cursor: pointer;
    }
    .auto-claim input[type='checkbox'] {
        margin-top: 3px;
        flex-shrink: 0;
        width: auto;
    }
    .ac-text {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    .ac-label {
        color: var(--text-primary);
        font-size: var(--fs-meta);
    }
    .ac-hint {
        color: var(--text-muted);
        font-size: 10.5px;
        line-height: 1.4;
    }
    .field-hint {
        margin-top: 2px;
        font-size: 10.5px;
        color: var(--text-faint);
    }
    .field-hint.warn { color: var(--state-error-fg); }
    .warning {
        margin: 0;
        padding: var(--s-3);
        background: var(--state-requested-bg);
        color: var(--state-requested-fg);
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
</style>
