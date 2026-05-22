<script lang="ts">
    /**
     * Wizard step 1 — identify the reciter.
     *
     * Tri-state toggle:
     *   • existing_combo   — reciter + already-covered (riwayah, style).
     *                        Routes to the per-delivery RequestForm flow.
     *   • existing_reciter — reciter exists; this is a new combination.
     *   • new              — reciter not in catalog.
     *
     * Picker uses an inline always-rendered list (not a popup) — simpler,
     * sidesteps focus/blur timing issues, and the picked combination row
     * pattern fits naturally below.
     *
     * Country field copies the `RequestForm.svelte` pattern verbatim
     * (datalist + focus-stash dance + ISO-2 resolution) so the UX matches.
     * TODO: extract to a shared CountryField component.
     */
    import { writable } from 'svelte/store';
    import { fade, fly } from 'svelte/transition';

    import { COUNTRIES, countryByName } from '../../../../lib/utils/countries';
    import { titleCaseSlug } from '../../../../lib/utils/delivery-label';
    import { match } from '../../../../lib/utils/fuzzy-match';
    import { catalogData } from '../../stores/catalog-data';
    import { openDetail } from '../../stores/dashboard-state';
    import { closeSubmitWizard, submitWizard } from '../../stores/submit-wizard';

    const queryStore = writable('');

    $: state = $submitWizard;
    $: mode = state.reciterMode;
    $: reciters = $catalogData.reciters;
    $: pickedReciter = state.existingReciterSlug
        ? (reciters.find((r) => r.reciter_id === state.existingReciterSlug) ?? null)
        : null;
    $: pickedCombo =
        pickedReciter && state.existingComboSlug
            ? (pickedReciter.deliveries.find((d) => d.slug === state.existingComboSlug) ?? null)
            : null;

    function computeFiltered(rs: typeof reciters, q: string): typeof reciters {
        if (!q) return rs.slice(0, 80);
        return rs
            .filter((r) => match(r.name, q) || (r.name_ar && match(r.name_ar, q)))
            .slice(0, 80);
    }
    $: filtered = computeFiltered(reciters, $queryStore);

    function setMode(next: typeof mode): void {
        submitWizard.update((s) => ({
            ...s,
            reciterMode: next,
            // Clear cross-mode state to avoid stale picks bleeding across.
            existingComboSlug: null,
        }));
    }

    function pickReciter(reciter_id: string): void {
        submitWizard.update((s) => ({
            ...s,
            existingReciterSlug: reciter_id,
            existingComboSlug: null,
        }));
        queryStore.set('');
    }

    function clearReciter(): void {
        submitWizard.update((s) => ({
            ...s,
            existingReciterSlug: null,
            existingComboSlug: null,
        }));
    }

    function pickCombo(slug: string): void {
        submitWizard.update((s) => ({ ...s, existingComboSlug: slug }));
    }

    function routeToRequestForm(): void {
        if (!pickedReciter) return;
        // Closes the wizard and opens the reciter-detail modal where the
        // RequestForm lives. The user clicks the chosen combination row
        // there → "Request alignment" surface them want.
        const reciter_id = pickedReciter.reciter_id;
        closeSubmitWizard();
        openDetail(reciter_id);
    }

    // ---- new-reciter fields ----
    function updateNew(field: 'name_en' | 'name_ar' | 'countryName', value: string): void {
        submitWizard.update((s) => ({
            ...s,
            newReciter: { ...s.newReciter, [field]: value },
        }));
    }

    // Live duplicate check for new reciters: fuzzy-match the typed name(s)
    // against the catalogue so near-spellings surface before submission.
    $: newNameEn = state.newReciter.name_en.trim();
    $: newNameAr = state.newReciter.name_ar.trim();
    $: dupCandidates =
        mode === 'new' && (newNameEn.length >= 2 || newNameAr.length >= 2)
            ? reciters
                  .filter(
                      (r) =>
                          (newNameEn.length >= 2 && match(r.name, newNameEn)) ||
                          (newNameAr.length >= 2 && !!r.name_ar && match(r.name_ar, newNameAr)),
                  )
                  .slice(0, 4)
            : [];

    // Country picker dance — copied from RequestForm.
    let countryFocusStash: string | null = null;
    $: countryName = state.newReciter.countryName;
    $: countryCode = countryByName(countryName)?.code ?? '';
    function onCountryFocus(): void {
        countryFocusStash = countryName;
        updateNew('countryName', '');
    }
    function onCountryBlur(): void {
        if (!countryName && countryFocusStash != null) {
            updateNew('countryName', countryFocusStash);
        }
        countryFocusStash = null;
    }
</script>

<div class="step" in:fade={{ duration: 180 }}>
    <div class="mode-toggle" role="tablist" aria-label="Reciter mode">
        <button
            type="button"
            class="mode-btn"
            class:active={mode === 'existing_combo'}
            role="tab"
            aria-selected={mode === 'existing_combo'}
            on:click={() => setMode('existing_combo')}
        >
            <span class="mode-label">Existing combination</span>
            <span class="mode-hint">edit metadata or request alignment</span>
        </button>
        <button
            type="button"
            class="mode-btn"
            class:active={mode === 'existing_reciter'}
            role="tab"
            aria-selected={mode === 'existing_reciter'}
            on:click={() => setMode('existing_reciter')}
        >
            <span class="mode-label">Existing reciter</span>
            <span class="mode-hint">new combination · {reciters.length} catalogued</span>
        </button>
        <button
            type="button"
            class="mode-btn"
            class:active={mode === 'new'}
            role="tab"
            aria-selected={mode === 'new'}
            on:click={() => setMode('new')}
        >
            <span class="mode-label">New reciter</span>
            <span class="mode-hint">not in the catalog yet</span>
        </button>
        <span class="mode-track" data-mode={mode} aria-hidden="true"></span>
    </div>

    {#if mode === 'existing_combo' || mode === 'existing_reciter'}
        <div class="pane" in:fly={{ y: 4, duration: 180 }}>
            {#if pickedReciter}
                <div class="picked">
                    <div class="picked-row">
                        <div class="picked-names">
                            <span class="picked-en">{pickedReciter.name}</span>
                            {#if pickedReciter.name_ar}
                                <span class="picked-ar" dir="rtl">{pickedReciter.name_ar}</span>
                            {/if}
                        </div>
                        <button type="button" class="picked-change" on:click={clearReciter}
                            >Change</button
                        >
                    </div>
                </div>

                {#if mode === 'existing_combo'}
                    <div class="combos-block" in:fade={{ duration: 200 }}>
                        <span class="combos-label">Pick the combination to edit</span>
                        <ul class="combo-list">
                            {#each pickedReciter.deliveries as d, i (d.slug)}
                                <li>
                                    <button
                                        type="button"
                                        class="combo-row"
                                        class:selected={d.slug === state.existingComboSlug}
                                        on:click={() => pickCombo(d.slug)}
                                        style:--row={i}
                                    >
                                        <span class="combo-tags">
                                            <span class="ct">{titleCaseSlug(d.riwayah)}</span>
                                            <span class="ct dim">·</span>
                                            <span class="ct">{titleCaseSlug(d.style)}</span>
                                            {#if d.recording_context}
                                                <span class="ct dim">·</span>
                                                <span class="ct dim"
                                                    >{titleCaseSlug(d.recording_context)}</span
                                                >
                                            {/if}
                                        </span>
                                        <span class="combo-meta">
                                            {d.chapter_count}/114
                                        </span>
                                    </button>
                                </li>
                            {/each}
                            {#if pickedReciter.deliveries.length === 0}
                                <li class="combo-empty">
                                    No combinations yet for this reciter — switch to "Existing
                                    reciter" to add the first.
                                </li>
                            {/if}
                        </ul>

                        {#if pickedCombo}
                            <div class="route-note" in:fade={{ duration: 160 }}>
                                Continue opens the reciter detail where the
                                <em>Request alignment</em> button lives for this combination.
                                <button
                                    type="button"
                                    class="route-btn"
                                    on:click={routeToRequestForm}>Open now ›</button
                                >
                            </div>
                        {/if}
                    </div>
                {:else if pickedReciter.deliveries.length > 0}
                    <div class="combos-block muted" in:fade={{ duration: 200 }}>
                        <span class="combos-label"
                            >Already covered (heads-up — pick a fresh combination on step 3)</span
                        >
                        <div class="combo-pills">
                            {#each pickedReciter.deliveries as d (d.slug)}
                                <span class="combo-pill">
                                    {titleCaseSlug(d.riwayah)} · {titleCaseSlug(d.style)}
                                </span>
                            {/each}
                        </div>
                    </div>
                {/if}
            {:else}
                <label class="picker">
                    <span class="picker-label">Reciter</span>
                    <input
                        type="text"
                        autocomplete="off"
                        placeholder="Type a name in Arabic or Latin…"
                        bind:value={$queryStore}
                    />
                </label>

                <ul class="results" role="listbox" aria-label="Reciter results">
                    {#if filtered.length === 0}
                        <li class="results-empty">
                            No match. Try a partial name, or switch to "New reciter".
                        </li>
                    {:else}
                        {#each filtered as r, i (r.reciter_id)}
                            <li>
                                <button
                                    type="button"
                                    class="result"
                                    on:click={() => pickReciter(r.reciter_id)}
                                    style:--row={i}
                                >
                                    <span class="r-name">{r.name}</span>
                                    {#if r.name_ar}
                                        <span class="r-name-ar" dir="rtl">{r.name_ar}</span>
                                    {/if}
                                    <span class="r-count">
                                        {r.deliveries.length}
                                        <span class="r-count-unit">combos</span>
                                    </span>
                                </button>
                            </li>
                        {/each}
                    {/if}
                </ul>
            {/if}
        </div>
    {:else}
        <div class="pane new" in:fly={{ y: 4, duration: 180 }}>
            <p class="dup-hint">
                Please double-check this reciter isn’t already in the catalog — even under a
                slightly different spelling. Search “Existing reciter” first if unsure.
            </p>
            <label>
                <span>English name</span>
                <input
                    type="text"
                    placeholder="Abdul-Basit Abdus-Samad"
                    value={state.newReciter.name_en}
                    on:input={(e) =>
                        updateNew('name_en', (e.currentTarget as HTMLInputElement).value)}
                />
            </label>
            <label class="rtl">
                <span>Arabic name</span>
                <input
                    type="text"
                    dir="rtl"
                    placeholder="عبد الباسط عبد الصمد"
                    value={state.newReciter.name_ar}
                    on:input={(e) =>
                        updateNew('name_ar', (e.currentTarget as HTMLInputElement).value)}
                />
            </label>
            <label class="country-field">
                <span>
                    Country
                    {#if countryCode}
                        <span class="label-meta">({countryCode})</span>
                    {:else if countryName}
                        <span class="label-meta warn">(unknown)</span>
                    {/if}
                </span>
                <input
                    type="text"
                    list="submit-wizard-countries"
                    placeholder="Start typing a country name…"
                    value={state.newReciter.countryName}
                    on:input={(e) =>
                        updateNew('countryName', (e.currentTarget as HTMLInputElement).value)}
                    on:focus={onCountryFocus}
                    on:blur={onCountryBlur}
                />
            </label>
            <datalist id="submit-wizard-countries">
                {#each COUNTRIES as c (c.code)}
                    <option value={c.name} label={c.code}></option>
                {/each}
            </datalist>

            {#if dupCandidates.length > 0}
                <div class="dup-matches" transition:fade={{ duration: 160 }}>
                    <span class="dup-matches-label">Possibly already in the catalog</span>
                    <ul>
                        {#each dupCandidates as r (r.reciter_id)}
                            <li>
                                <button type="button" class="dup-row" on:click={() => { setMode('existing_reciter'); pickReciter(r.reciter_id); }}>
                                    <span class="dup-name">{r.name}</span>
                                    {#if r.name_ar}<span class="dup-ar" dir="rtl">{r.name_ar}</span>{/if}
                                    <span class="dup-use">Use this →</span>
                                </button>
                            </li>
                        {/each}
                    </ul>
                </div>
            {/if}
        </div>
    {/if}
</div>

<style>
    .step {
        display: flex;
        flex-direction: column;
        gap: var(--s-4);
    }

    /* tri-state toggle */
    .mode-toggle {
        position: relative;
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        padding: 3px;
    }
    .mode-btn {
        position: relative;
        z-index: 1;
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 2px;
        padding: var(--s-2) var(--s-3);
        border-radius: 4px;
        color: var(--text-muted);
        text-align: left;
        transition: color var(--t-base) var(--ease-out-quart);
    }
    .mode-btn.active {
        color: var(--text-primary);
    }
    .mode-label {
        font-size: var(--fs-meta);
        font-weight: 500;
    }
    .mode-hint {
        font-size: 10.5px;
        color: var(--text-faint);
    }
    .mode-track {
        position: absolute;
        top: 3px;
        bottom: 3px;
        width: calc(100% / 3 - 3px);
        left: 3px;
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: 4px;
        transition: transform var(--t-base) var(--ease-out-expo);
        pointer-events: none;
    }
    .mode-track[data-mode='existing_reciter'] {
        transform: translateX(100%);
    }
    .mode-track[data-mode='new'] {
        transform: translateX(200%);
    }

    .pane {
        display: flex;
        flex-direction: column;
        gap: var(--s-3);
    }
    .pane.new {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: var(--s-3);
    }
    .pane.new .country-field {
        grid-column: 1 / -1;
    }
    .dup-hint {
        grid-column: 1 / -1;
        margin: 0;
        font-size: 11px;
        color: var(--text-faint);
        line-height: 1.5;
    }
    .dup-matches {
        grid-column: 1 / -1;
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
        padding: var(--s-3);
        background: oklch(0.86 0.13 75 / 0.1);
        border: 1px solid oklch(0.86 0.13 75 / 0.35);
        border-radius: var(--r-2);
    }
    .dup-matches-label {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--state-error-fg);
    }
    .dup-matches ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
    .dup-row {
        width: 100%;
        display: flex;
        align-items: baseline;
        gap: var(--s-2);
        padding: 5px 8px;
        border-radius: var(--r-1);
        text-align: left;
        color: var(--text-secondary);
        transition: background var(--t-fast);
    }
    .dup-row:hover { background: var(--panel); }
    .dup-name { font-size: var(--fs-body); color: var(--text-primary); }
    .dup-ar { font-size: var(--fs-meta); color: var(--text-secondary); }
    .dup-use { margin-left: auto; font-size: 10.5px; color: var(--accent); }

    label {
        display: flex;
        flex-direction: column;
        gap: 4px;
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }
    label.rtl input {
        text-align: right;
    }
    input {
        background: var(--panel);
        border: 1px solid var(--border-default);
        color: var(--text-primary);
        border-radius: var(--r-2);
        padding: 8px 10px;
        font: inherit;
        transition:
            border-color var(--t-fast),
            background var(--t-fast);
    }
    input::placeholder {
        color: var(--text-faint);
    }
    input:focus {
        outline: none;
        border-color: var(--accent);
        background: var(--panel-2);
    }
    .label-meta {
        margin-left: 4px;
        font-size: 10.5px;
        color: var(--text-faint);
        font-variant-numeric: tabular-nums;
    }
    .label-meta.warn {
        color: var(--state-error-fg);
    }

    /* picker + inline results list */
    .picker {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    .picker-label {
        color: var(--text-muted);
        font-size: var(--fs-meta);
    }

    .results {
        list-style: none;
        margin: 0;
        padding: 4px;
        max-height: 240px;
        overflow-y: auto;
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    .results-empty {
        padding: var(--s-3);
        font-size: var(--fs-meta);
        color: var(--text-faint);
        text-align: center;
    }
    .result {
        width: 100%;
        display: grid;
        grid-template-columns: 1fr auto auto;
        align-items: baseline;
        column-gap: var(--s-3);
        padding: 6px 8px;
        border-radius: var(--r-1);
        color: var(--text-secondary);
        text-align: left;
        transition:
            background var(--t-fast),
            color var(--t-fast);
        animation: row-in 220ms var(--ease-out-quart) both;
        animation-delay: calc(var(--row) * 12ms);
    }
    @keyframes row-in {
        from {
            opacity: 0;
            transform: translateY(-2px);
        }
        to {
            opacity: 1;
            transform: none;
        }
    }
    .result:hover {
        background: var(--accent-tint-soft);
        color: var(--text-primary);
    }
    .r-name {
        font-size: var(--fs-body);
        color: var(--text-primary);
    }
    .r-name-ar {
        font-size: var(--fs-body);
        color: var(--text-secondary);
    }
    .r-count {
        font-family: var(--font-mono);
        font-size: 10.5px;
        color: var(--text-faint);
        font-variant-numeric: tabular-nums;
    }
    .r-count-unit {
        color: var(--text-faint);
        margin-left: 3px;
    }

    /* picked reciter chip */
    .picked {
        padding: var(--s-3);
        background: var(--accent-tint-soft);
        border: 1px solid var(--accent-tint);
        border-radius: var(--r-2);
    }
    .picked-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-3);
    }
    .picked-names {
        display: flex;
        align-items: baseline;
        gap: var(--s-3);
        min-width: 0;
        flex-wrap: wrap;
    }
    .picked-en {
        font-size: var(--fs-body);
        font-weight: 500;
        color: var(--text-primary);
    }
    .picked-ar {
        font-size: var(--fs-body);
        color: var(--text-secondary);
    }
    .picked-change {
        flex-shrink: 0;
        font-size: 10.5px;
        color: var(--text-muted);
        padding: 4px 10px;
        border: 1px solid var(--border-default);
        border-radius: var(--r-2);
        transition:
            color var(--t-fast),
            border-color var(--t-fast);
    }
    .picked-change:hover {
        color: var(--text-primary);
        border-color: var(--accent);
    }

    /* combos block */
    .combos-block {
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
    }
    .combos-block.muted {
        padding: var(--s-3);
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
    }
    .combos-label {
        font-size: 10.5px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--text-muted);
    }
    .combo-list {
        list-style: none;
        margin: 0;
        padding: 4px;
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        display: flex;
        flex-direction: column;
        gap: 2px;
        max-height: 240px;
        overflow-y: auto;
    }
    .combo-row {
        width: 100%;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-3);
        padding: 8px 10px;
        border: 1px solid transparent;
        border-radius: var(--r-1);
        color: var(--text-secondary);
        text-align: left;
        transition:
            background var(--t-fast),
            border-color var(--t-fast);
        animation: row-in 200ms var(--ease-out-quart) both;
        animation-delay: calc(var(--row) * 18ms);
    }
    .combo-row:hover {
        background: var(--panel);
        border-color: var(--border-quiet);
    }
    .combo-row.selected {
        background: var(--accent-tint-soft);
        border-color: var(--accent);
        color: var(--text-primary);
    }
    .combo-tags {
        display: inline-flex;
        align-items: baseline;
        gap: 6px;
        font-family: var(--font-mono);
        font-size: 12px;
    }
    .combo-tags .ct.dim {
        color: var(--text-faint);
    }
    .combo-meta {
        font-family: var(--font-mono);
        font-size: 10.5px;
        color: var(--text-faint);
        font-variant-numeric: tabular-nums;
    }
    .combo-empty {
        padding: var(--s-3);
        font-size: var(--fs-meta);
        color: var(--text-faint);
        font-style: italic;
        text-align: center;
    }
    .combo-pills {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
    }
    .combo-pill {
        display: inline-flex;
        padding: 2px 8px;
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: 999px;
        color: var(--text-muted);
        font-size: 10.5px;
        font-family: var(--font-mono);
    }

    .route-note {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-3);
        padding: var(--s-3);
        background: var(--panel);
        border: 1px solid var(--accent-tint);
        border-radius: var(--r-2);
        font-size: var(--fs-meta);
        color: var(--text-secondary);
    }
    .route-note em {
        font-style: normal;
        font-family: var(--font-mono);
        font-size: 11px;
        padding: 1px 5px;
        border-radius: var(--r-1);
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        color: var(--text-primary);
    }
    .route-btn {
        flex-shrink: 0;
        font-size: var(--fs-meta);
        color: var(--accent);
        padding: 4px 10px;
        border: 1px solid var(--accent);
        border-radius: var(--r-2);
        transition:
            background var(--t-fast),
            color var(--t-fast);
    }
    .route-btn:hover {
        background: var(--accent);
        color: var(--accent-fg);
    }
</style>
