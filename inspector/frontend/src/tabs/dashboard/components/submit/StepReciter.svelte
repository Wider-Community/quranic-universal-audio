<script lang="ts">
    /**
     * Wizard step 1 — identify the reciter.
     *
     * Two modes:
     *   • existing — fuzzy-matched typeahead over the loaded catalog,
     *     with the picked reciter's already-covered combinations shown
     *     below as muted pills. Picking a combination collision raises
     *     the parent banner's `highlighted` flag.
     *   • new — three text fields (English name, Arabic RTL name,
     *     country via the same datalist as RequestForm).
     *
     * The mode toggle cross-fades between the two field groups; the
     * picker's results list animates in via a staggered fade.
     */
    import { fade, fly } from 'svelte/transition';
    import { writable } from 'svelte/store';

    import { catalogData } from '../../stores/catalog-data';
    import { submitWizard } from '../../stores/submit-wizard';
    import { match } from '../../../../lib/utils/fuzzy-match';
    import { COUNTRIES } from '../../../../lib/utils/countries';
    import { titleCaseSlug } from '../../../../lib/utils/delivery-label';

    // Local store-backed UI state. We use stores (rather than `let`) because
    // Svelte 5's legacy-mode reactivity has surprising holes for local `let`
    // when mutated inside event handlers — stores are immune.
    const queryStore = writable('');
    const showSuggestionsStore = writable(false);
    let inputEl: HTMLInputElement | null = null;

    $: state = $submitWizard;
    $: mode = state.reciterMode;
    $: reciters = $catalogData.reciters;
    $: pickedReciter = state.existingReciterSlug
        ? reciters.find((r) => r.slug === state.existingReciterSlug) ?? null
        : null;

    // When a reciter is locked in we want the input to show their name.
    let lastPickedSlug: string | null = null;
    $: if (pickedReciter && pickedReciter.slug !== lastPickedSlug && !$showSuggestionsStore) {
        queryStore.set(pickedReciter.name);
        lastPickedSlug = pickedReciter.slug;
    } else if (!pickedReciter) {
        lastPickedSlug = null;
    }

    function computeFiltered(rs: typeof reciters, q: string): typeof reciters {
        if (!q) return rs.slice(0, 50);
        return rs
            .filter((r) => match(r.name, q) || (r.name_ar && match(r.name_ar, q)))
            .slice(0, 50);
    }
    $: filtered = computeFiltered(reciters, $queryStore);

    function setMode(next: 'existing' | 'new'): void {
        submitWizard.update((s) => ({ ...s, reciterMode: next }));
    }

    function pickReciter(slug: string): void {
        submitWizard.update((s) => ({ ...s, existingReciterSlug: slug }));
        showSuggestionsStore.set(false);
        queryStore.set('');
        inputEl?.blur();
    }

    function clearPick(): void {
        submitWizard.update((s) => ({ ...s, existingReciterSlug: null }));
        queryStore.set('');
        showSuggestionsStore.set(true);
        inputEl?.focus();
    }

    function onInput(): void {
        showSuggestionsStore.set(true);
        if (pickedReciter) {
            submitWizard.update((s) => ({ ...s, existingReciterSlug: null }));
        }
    }

    function onFocus(): void {
        showSuggestionsStore.set(true);
    }

    function onBlur(): void {
        setTimeout(() => { showSuggestionsStore.set(false); }, 120);
    }

    function updateNew(field: 'name_en' | 'name_ar' | 'countryName', value: string): void {
        submitWizard.update((s) => ({
            ...s,
            newReciter: { ...s.newReciter, [field]: value },
        }));
    }
</script>

<div class="step" in:fade={{ duration: 180 }}>
    <p class="lede">
        We accept local files, direct links, or a playlist URL —
        pick how on the next step. First, who's reciting?
    </p>

    <div class="mode-toggle" role="tablist" aria-label="Reciter mode">
        <button
            type="button"
            class="mode-btn"
            class:active={mode === 'existing'}
            role="tab"
            aria-selected={mode === 'existing'}
            on:click={() => setMode('existing')}
        >
            <span class="mode-label">Existing reciter</span>
            <span class="mode-hint">{reciters.length} in catalog</span>
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

    {#if mode === 'existing'}
        <div class="pane" in:fly={{ y: 4, duration: 180 }}>
            <label class="picker">
                <span class="picker-label">Reciter</span>
                <div class="picker-shell" class:has-pick={!!pickedReciter}>
                    <input
                        bind:this={inputEl}
                        type="text"
                        autocomplete="off"
                        placeholder="Type a name in Arabic or Latin…"
                        bind:value={$queryStore}
                        on:input={onInput}
                        on:focus={onFocus}
                        on:blur={onBlur}
                    />
                    {#if pickedReciter && !$showSuggestionsStore}
                        <button
                            type="button"
                            class="clear-pick"
                            aria-label="Clear selection"
                            on:click={clearPick}
                        >×</button>
                    {/if}
                </div>

                {#if $showSuggestionsStore && filtered.length > 0}
                    <ul class="suggestions" role="listbox" transition:fly={{ y: -4, duration: 140 }}>
                        {#each filtered as r, i (r.slug)}
                            <li
                                role="option"
                                aria-selected={r.slug === state.existingReciterSlug}
                                style:--row={i}
                            >
                                <button
                                    type="button"
                                    class="suggestion"
                                    on:click={() => pickReciter(r.slug)}
                                >
                                    <span class="s-name">{r.name}</span>
                                    {#if r.name_ar}
                                        <span class="s-name-ar" dir="rtl">{r.name_ar}</span>
                                    {/if}
                                    <span class="s-count">
                                        {r.deliveries.length}
                                        <span class="s-count-unit">combinations</span>
                                    </span>
                                </button>
                            </li>
                        {/each}
                    </ul>
                {/if}
            </label>

            {#if pickedReciter}
                <div class="combos" in:fade={{ duration: 200 }}>
                    <span class="combos-label">Already covered</span>
                    <div class="combos-row">
                        {#each pickedReciter.deliveries as d, i (d.slug)}
                            <span
                                class="combo-pill"
                                style:--row={i}
                                in:fly={{ y: 3, duration: 220, delay: 40 + i * 22 }}
                            >
                                {titleCaseSlug(d.riwayah)} · {titleCaseSlug(d.style)}
                                {#if d.recording_context}
                                    <span class="combo-context">· {titleCaseSlug(d.recording_context)}</span>
                                {/if}
                            </span>
                        {/each}
                        {#if pickedReciter.deliveries.length === 0}
                            <span class="combos-empty">No combinations yet — you're contributing the first.</span>
                        {/if}
                    </div>
                </div>
            {/if}
        </div>
    {:else}
        <div class="pane new" in:fly={{ y: 4, duration: 180 }}>
            <label>
                <span>English name</span>
                <input
                    type="text"
                    placeholder="Abdul-Basit Abdus-Samad"
                    value={state.newReciter.name_en}
                    on:input={(e) => updateNew('name_en', (e.currentTarget as HTMLInputElement).value)}
                />
            </label>
            <label class="rtl">
                <span>Arabic name</span>
                <input
                    type="text"
                    dir="rtl"
                    placeholder="عبد الباسط عبد الصمد"
                    value={state.newReciter.name_ar}
                    on:input={(e) => updateNew('name_ar', (e.currentTarget as HTMLInputElement).value)}
                />
            </label>
            <label>
                <span>Country</span>
                <input
                    type="text"
                    list="submit-wizard-countries"
                    placeholder="Start typing…"
                    value={state.newReciter.countryName}
                    on:input={(e) => updateNew('countryName', (e.currentTarget as HTMLInputElement).value)}
                />
            </label>
            <datalist id="submit-wizard-countries">
                {#each COUNTRIES as c (c.code)}
                    <option value={c.name} label={c.code}></option>
                {/each}
            </datalist>
        </div>
    {/if}
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
        line-height: 1.55;
        max-width: 60ch;
    }

    .mode-toggle {
        position: relative;
        display: grid;
        grid-template-columns: 1fr 1fr;
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
    .mode-btn.active { color: var(--text-primary); }
    .mode-label {
        font-size: var(--fs-body);
        font-weight: 500;
    }
    .mode-hint {
        font-size: 10.5px;
        color: var(--text-faint);
        font-variant-numeric: tabular-nums;
    }
    .mode-track {
        position: absolute;
        top: 3px;
        bottom: 3px;
        width: calc(50% - 3px);
        left: 3px;
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: 4px;
        transition: transform var(--t-base) var(--ease-out-expo);
        pointer-events: none;
    }
    .mode-track[data-mode='new'] { transform: translateX(100%); }

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
    .pane.new label:last-of-type { grid-column: 1 / -1; }

    label {
        display: flex;
        flex-direction: column;
        gap: 4px;
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }
    label.rtl input { text-align: right; }
    input {
        background: var(--panel);
        border: 1px solid var(--border-default);
        color: var(--text-primary);
        border-radius: var(--r-2);
        padding: 8px 10px;
        font: inherit;
        transition: border-color var(--t-fast), background var(--t-fast);
    }
    input::placeholder { color: var(--text-faint); }
    input:focus {
        outline: none;
        border-color: var(--accent);
        background: var(--panel-2);
    }

    .picker {
        position: relative;
    }
    .picker-label {
        color: var(--text-muted);
        font-size: var(--fs-meta);
        margin-bottom: 4px;
    }
    .picker-shell {
        position: relative;
    }
    .picker-shell.has-pick input {
        border-color: var(--accent);
        background: var(--accent-tint-soft);
    }
    .clear-pick {
        position: absolute;
        right: 8px;
        top: 50%;
        transform: translateY(-50%);
        width: 22px;
        height: 22px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        color: var(--text-muted);
        border-radius: var(--r-1);
        font-size: 14px;
    }
    .clear-pick:hover {
        color: var(--text-primary);
        background: var(--panel);
    }

    .suggestions {
        position: absolute;
        z-index: 5;
        top: calc(100% + 4px);
        left: 0;
        right: 0;
        max-height: 280px;
        overflow-y: auto;
        list-style: none;
        margin: 0;
        padding: 4px;
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-2);
        box-shadow: 0 16px 32px oklch(0 0 0 / 0.32);
    }
    .suggestions li {
        animation: row-in 220ms var(--ease-out-quart) both;
        animation-delay: calc(var(--row) * 18ms);
    }
    @keyframes row-in {
        from { opacity: 0; transform: translateY(-3px); }
        to   { opacity: 1; transform: none; }
    }
    .suggestion {
        width: 100%;
        display: grid;
        grid-template-columns: 1fr auto auto;
        align-items: baseline;
        column-gap: var(--s-3);
        padding: 6px 8px;
        border-radius: var(--r-1);
        color: var(--text-secondary);
        text-align: left;
        transition: background var(--t-fast), color var(--t-fast);
    }
    .suggestion:hover {
        background: var(--accent-tint-soft);
        color: var(--text-primary);
    }
    .s-name { font-size: var(--fs-body); color: var(--text-primary); }
    .s-name-ar { font-size: var(--fs-body); color: var(--text-secondary); }
    .s-count {
        font-family: var(--font-mono);
        font-size: 10.5px;
        color: var(--text-faint);
        font-variant-numeric: tabular-nums;
    }
    .s-count-unit { color: var(--text-faint); margin-left: 3px; }

    .combos {
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
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
    .combos-row {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
    }
    .combo-pill {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 3px 8px;
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: 999px;
        color: var(--text-secondary);
        font-size: 11px;
        font-family: var(--font-mono);
    }
    .combo-context { color: var(--text-faint); }
    .combos-empty {
        font-size: var(--fs-meta);
        color: var(--text-muted);
        font-style: italic;
    }
</style>
