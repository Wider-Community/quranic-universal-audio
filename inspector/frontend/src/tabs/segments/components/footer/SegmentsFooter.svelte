<script lang="ts">
    /**
     * SegmentsFooter — single pinned-bottom bar for the Segments tab.
     *
     * Combines reciter identity + state pill, surah/ayah location pickers,
     * and the action cluster (claim, unclaim, mark-ready, save, auto-save,
     * history) into one row. Replaces the earlier split between
     * ReciterContextChip and the .seg-selector-bar info-bar.
     *
     * Reads tab-scoped stores directly; mutating coordination (reciter
     * task refresh, chapter load, verse jump, picker change) is bubbled
     * to the parent via events so SegmentsTab stays the single owner of
     * the reciter-task subscription and chapter/verse data fetches.
     */
    import { createEventDispatcher, onMount, tick } from 'svelte';
    import { get } from 'svelte/store';

    import { clickOutside } from '../../../../lib/actions/click-outside';
    import type { ReciterTask } from '../../../../lib/api/reciter-task';
    import ClaimButton from '../../../../lib/components/ClaimButton.svelte';
    import CombinationPicker, {
        type CombinationSelection,
    } from '../../../../lib/components/picker/CombinationPicker.svelte';
    import SurahPopover from '../../../../lib/components/player/SurahPopover.svelte';
    import StatePill from '../../../../lib/components/StatePill.svelte';
    import { editingMode } from '../../../../lib/stores/editing-mode';
    import type { PublicBucket } from '../../../../lib/types/public-state';
    import { titleCaseSlug } from '../../../../lib/utils/delivery-label';
    import { autoSaveEnabled, toggleAutoSave } from '../../stores/autosave';
    import {
        selectedChapter,
        selectedReciter,
        selectedVerse,
        verseOptions,
    } from '../../stores/chapter';
    import { isDirtyStore } from '../../stores/dirty';
    import { historyLoadState, historyVisible } from '../../stores/history';
    import { saveButtonLabel, savePreviewVisible } from '../../stores/save';
    import { hideHistoryView, showHistoryView } from '../../utils/history/actions';
    import { confirmSaveFromPreview, hideSavePreview, onSegSaveClick } from '../../utils/save/actions';

    export let reciterTask: ReciterTask | null = null;
    export let chipActionBusy: '' | 'unclaim' | 'mark' = '';
    export let contextName: string | null = null;
    export let contextBucket: PublicBucket | null = null;
    export let contextRiwayah: string | null = null;
    export let contextStyle: string | null = null;

    const dispatch = createEventDispatcher<{
        reciterChange: {
            slug: string;
            name: string;
            bucket: PublicBucket;
            riwayah: string;
            style: string;
        };
        chapterChange: string;
        verseJump: string;
        unclaim: void;
        markReady: void;
        claimed: void;
    }>();

    let pickerOpen = false;
    let surahOpen = false;
    let ayahOpen = false;
    let ayahFilterInput: HTMLInputElement | null = null;
    let ayahQuery = '';
    let footerEl: HTMLDivElement | null = null;

    onMount(() => {
        // Publish the live footer height as `--seg-footer-h` on the document
        // root so the segments panel's `padding-bottom` keeps up when the
        // footer stacks at narrow widths (identity / location / actions on
        // three rows). The mediaquery-driven layout already changes height;
        // measuring keeps the cushion correct without duplicated breakpoints.
        if (!footerEl) return;
        // Publishes to `--seg-footer-actual-h` for consumers (the panel's
        // padding-bottom). Distinct from `--seg-footer-h` which is the
        // *target* min-height the footer sizes itself against, to avoid a
        // feedback loop where reading and writing the same var ratchets the
        // footer height upward on every observation.
        const apply = () => {
            if (!footerEl) return;
            document.documentElement.style.setProperty(
                '--seg-footer-actual-h',
                `${footerEl.offsetHeight}px`,
            );
        };
        apply();
        const ro = new ResizeObserver(apply);
        ro.observe(footerEl);
        return () => {
            ro.disconnect();
            document.documentElement.style.removeProperty('--seg-footer-actual-h');
        };
    });

    $: hasReciter = !!$selectedReciter;
    $: chipMeta = [titleCaseSlug(contextRiwayah), titleCaseSlug(contextStyle)]
        .filter(Boolean)
        .join(' · ');

    // Full 1..114 range — surah availability per reciter would tighten this
    // later if we surface per-reciter chapter manifests in the catalog.
    const allSurahs: number[] = Array.from({ length: 114 }, (_, i) => i + 1);

    $: filteredAyahs = ayahQuery.trim()
        ? $verseOptions.filter((v) => String(v).startsWith(ayahQuery.trim()))
        : $verseOptions;

    $: historyButtonLabel = $historyVisible
        ? 'Back'
        : $historyLoadState === 'loading'
            ? 'History…'
            : 'History';

    function onPickerSelect(ev: CustomEvent<CombinationSelection>): void {
        const { reciter, delivery } = ev.detail;
        dispatch('reciterChange', {
            slug: delivery.slug,
            name: reciter.name,
            bucket: delivery.bucket,
            riwayah: delivery.riwayah,
            style: delivery.style,
        });
        pickerOpen = false;
    }

    function onSurahPick(ev: CustomEvent<number>): void {
        surahOpen = false;
        dispatch('chapterChange', String(ev.detail));
    }

    async function openAyah(): Promise<void> {
        if (!$selectedChapter) return;
        ayahQuery = '';
        ayahOpen = true;
        await tick();
        ayahFilterInput?.focus();
    }

    function onAyahPick(v: number): void {
        ayahOpen = false;
        dispatch('verseJump', String(v));
    }

    function onAyahKey(ev: KeyboardEvent): void {
        if (ev.key === 'Enter' && filteredAyahs.length > 0) {
            onAyahPick(filteredAyahs[0]!);
        }
    }

    function onUnclaim(): void {
        if (chipActionBusy) return;
        dispatch('unclaim');
    }
    function onMarkReady(): void {
        if (chipActionBusy) return;
        dispatch('markReady');
    }
    function onClaimed(): void {
        dispatch('claimed');
    }

    function toggleHistory(): void {
        if ($historyVisible) hideHistoryView();
        else showHistoryView();
    }

    $: writeable = $editingMode.kind !== 'view';
    $: showSavePreview = $savePreviewVisible;
    $: saveDisabled = $autoSaveEnabled || !$isDirtyStore;
    $: saveLabel = $isDirtyStore
        ? ($autoSaveEnabled && get(saveButtonLabel) === 'Save' ? 'Saving…' : $saveButtonLabel)
        : 'Saved';
</script>

<div class="segs-footer" class:is-empty={!hasReciter} bind:this={footerEl}>
    <div class="zone zone-identity">
        <button
            type="button"
            class="identity"
            class:placeholder={!hasReciter}
            on:click={() => (pickerOpen = true)}
            aria-haspopup="dialog"
            title={hasReciter ? 'Switch reciter' : 'Pick a reciter'}
        >
            <span class="identity-name">
                {contextName ?? (hasReciter ? 'Loading…' : 'Pick a reciter')}
            </span>
            {#if chipMeta}
                <span class="identity-meta">{chipMeta}</span>
            {/if}
            {#if contextBucket}
                <StatePill state={contextBucket} size="sm" />
            {/if}
            <span class="identity-switch" aria-hidden="true">⇄</span>
        </button>

        {#if hasReciter && !showSavePreview}
            <div class="reciter-actions">
                <ClaimButton
                    slug={$selectedReciter || ''}
                    task={reciterTask}
                    onClaimed={onClaimed}
                />
                {#if reciterTask?.predicates.can_mark_ready}
                    <button
                        type="button"
                        class="action ghost-accent"
                        disabled={chipActionBusy !== ''}
                        title="Mark this reciter ready for a maintainer to publish"
                        on:click={onMarkReady}
                    >Mark ready</button>
                {/if}
                {#if reciterTask?.predicates.can_release}
                    <button
                        type="button"
                        class="action ghost"
                        disabled={chipActionBusy !== ''}
                        on:click={onUnclaim}
                    >Unclaim</button>
                {/if}
            </div>
        {/if}
    </div>

    {#if hasReciter}
        <div class="zone zone-location" use:clickOutside={() => { surahOpen = false; ayahOpen = false; }}>
            <button
                type="button"
                class="loc-trigger"
                class:has-value={!!$selectedChapter}
                on:click={() => { surahOpen = !surahOpen; ayahOpen = false; }}
                aria-haspopup="dialog"
                aria-expanded={surahOpen}
            >
                <span class="loc-label">Surah</span>
                {#if $selectedChapter}
                    <span class="loc-value">{$selectedChapter}</span>
                {:else}
                    <span class="loc-empty">—</span>
                {/if}
                <span class="chev" aria-hidden="true">▾</span>
            </button>
            <button
                type="button"
                class="loc-trigger"
                class:has-value={!!$selectedVerse}
                disabled={!$selectedChapter}
                on:click={openAyah}
                aria-haspopup="dialog"
                aria-expanded={ayahOpen}
            >
                <span class="loc-label">Ayah</span>
                {#if $selectedVerse}
                    <span class="loc-value">{$selectedVerse}</span>
                {:else}
                    <span class="loc-empty">all</span>
                {/if}
                <span class="chev" aria-hidden="true">▾</span>
            </button>

            {#if surahOpen}
                <div class="pop pop-surah">
                    <SurahPopover
                        surahNums={allSurahs}
                        value={$selectedChapter ? parseInt($selectedChapter) : null}
                        on:change={onSurahPick}
                    />
                </div>
            {/if}

            {#if ayahOpen}
                <div class="pop pop-ayah" role="dialog" aria-label="Ayah picker">
                    <input
                        bind:this={ayahFilterInput}
                        bind:value={ayahQuery}
                        on:keydown={onAyahKey}
                        class="ayah-search"
                        type="text"
                        inputmode="numeric"
                        placeholder="Jump to ayah…"
                        autocomplete="off"
                    />
                    <div class="ayah-grid" role="listbox">
                        {#each filteredAyahs as v (v)}
                            <button
                                type="button"
                                class="ayah-cell"
                                class:active={String(v) === $selectedVerse}
                                role="option"
                                aria-selected={String(v) === $selectedVerse}
                                on:click={() => onAyahPick(v)}
                            >{v}</button>
                        {:else}
                            <div class="empty">No matches</div>
                        {/each}
                    </div>
                </div>
            {/if}
        </div>
    {:else}
        <div class="zone zone-location empty-spacer" aria-hidden="true"></div>
    {/if}

    <div class="zone zone-save">
        {#if hasReciter}
            {#if showSavePreview}
                <button class="action ghost" on:click={() => hideSavePreview()}>Cancel</button>
                <button class="action primary" on:click={confirmSaveFromPreview}>Confirm save</button>
            {:else}
                <button
                    type="button"
                    class="utility"
                    class:on={$historyVisible}
                    title={$historyVisible ? 'Back to segments' : 'History'}
                    aria-label={historyButtonLabel}
                    on:click={toggleHistory}
                >
                    {#if $historyVisible}
                        <span class="util-glyph">←</span>
                        <span class="util-label">Back</span>
                    {:else}
                        <span class="util-glyph" aria-hidden="true">
                            <!-- clock-rewind glyph -->
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                                <path d="M3 12a9 9 0 1 0 3-6.7" />
                                <path d="M3 4v5h5" />
                                <path d="M12 7v5l3 2" />
                            </svg>
                        </span>
                        <span class="util-label">History</span>
                    {/if}
                </button>

                {#if writeable}
                    <div class="save-group">
                        <button
                            type="button"
                            class="autosave-toggle"
                            class:on={$autoSaveEnabled}
                            aria-pressed={$autoSaveEnabled}
                            title={$autoSaveEnabled ? 'Auto-save on — click to disable' : 'Auto-save off — click to enable'}
                            on:click={() => toggleAutoSave(!$autoSaveEnabled)}
                        >
                            <span class="autosave-glyph" aria-hidden="true">
                                <!-- lightning-bolt for "auto" -->
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                                    <path d="M13 2 3 14h7l-1 8 10-12h-7l1-8Z" />
                                </svg>
                            </span>
                            <span>Auto</span>
                        </button>

                        <button
                            type="button"
                            class="action save"
                            class:primary={$isDirtyStore && !$autoSaveEnabled}
                            class:saved={!$isDirtyStore}
                            class:auto-busy={$autoSaveEnabled && $isDirtyStore}
                            disabled={saveDisabled}
                            on:click={onSegSaveClick}
                        >
                            {#if !$isDirtyStore}
                                <span class="save-glyph" aria-hidden="true">✓</span>
                                <span>Saved</span>
                            {:else if $autoSaveEnabled}
                                <span class="save-pulse" aria-hidden="true"></span>
                                <span>Auto-saving…</span>
                            {:else}
                                <span>{saveLabel}</span>
                            {/if}
                        </button>
                    </div>
                {/if}
            {/if}
        {/if}
    </div>
</div>

{#if pickerOpen}
    <CombinationPicker
        open={pickerOpen}
        title="Switch reciter"
        on:select={onPickerSelect}
        on:close={() => (pickerOpen = false)}
    />
{/if}

<style>
    .segs-footer {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        z-index: 100;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-3);
        padding: var(--s-2) var(--s-4);
        min-height: var(--seg-footer-h, 60px);
        background: var(--panel);
        border-top: 1px solid var(--border-default);
        box-shadow: 0 -8px 24px oklch(0 0 0 / 0.28);
    }
    /* Location is pinned to the true viewport horizontal center, decoupled
       from the side zones' widths. Identity (left) and Save (right) flex
       naturally; reservation gutters on either side of those zones keep
       them from sliding under the popovers. */
    .zone-location {
        position: absolute;
        left: 50%;
        top: 50%;
        transform: translate(-50%, -50%);
    }

    .zone {
        min-width: 0;
        display: flex;
        align-items: center;
    }
    .zone-identity {
        justify-content: flex-start;
        gap: var(--s-3);
        flex-wrap: nowrap;
    }
    .zone-location {
        justify-content: center;
        gap: var(--s-2);
    }
    .zone-save {
        justify-content: flex-end;
        gap: var(--s-2);
        flex-wrap: wrap;
    }
    .empty-spacer { display: none; }

    /* Cluster of reciter-state actions (Claim / Mark ready / Unclaim) that
       sits to the right of the identity chip. Visually attached — the
       chip is the subject these actions operate on. */
    .reciter-actions {
        display: inline-flex;
        align-items: center;
        gap: var(--s-2);
        flex: 0 0 auto;
    }
    .save-group {
        display: inline-flex;
        align-items: center;
        gap: var(--s-2);
    }

    /* ---------- Identity ---------- */
    .identity {
        display: inline-flex;
        align-items: center;
        gap: var(--s-3);
        max-width: 100%;
        min-width: 0;
        /* Shrink to fit content; never expand to fill the zone. The grid
           column itself is `auto`-sized so the chip stays the width of its
           name + meta + pill, not stretched to a fraction of the viewport. */
        flex: 0 1 auto;
        padding: 6px var(--s-3);
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-3);
        color: inherit;
        cursor: pointer;
        font: inherit;
        transition: border-color var(--t-fast), background var(--t-fast);
    }
    .identity:hover { border-color: var(--border-strong); background: var(--panel); }
    .identity:focus-visible { outline: none; border-color: var(--accent); }
    .identity.placeholder {
        background: var(--accent-tint-soft);
        border-color: oklch(0.785 0.130 220 / 0.35);
        color: var(--accent);
    }
    .identity.placeholder:hover { background: var(--accent-tint); }

    .identity-name {
        flex: 0 1 auto;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-size: var(--fs-row);
        font-weight: 500;
        color: var(--text-primary);
    }
    .placeholder .identity-name { color: inherit; font-weight: 600; }
    .identity-meta {
        flex: 0 1 auto;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }
    .identity-switch {
        margin-inline-start: auto;
        padding-inline-start: var(--s-2);
        color: var(--text-faint);
        font-size: var(--fs-meta);
        transition: color var(--t-fast);
    }
    .identity:hover .identity-switch { color: var(--text-secondary); }

    /* ---------- Location ---------- */
    .loc-trigger {
        display: inline-flex;
        align-items: baseline;
        gap: 6px;
        padding: 6px var(--s-3);
        background: transparent;
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        color: var(--text-secondary);
        cursor: pointer;
        font: inherit;
        font-size: var(--fs-meta);
        transition: border-color var(--t-fast), color var(--t-fast), background var(--t-fast);
    }
    .loc-trigger:hover:not(:disabled) {
        border-color: var(--border-strong);
        color: var(--text-primary);
    }
    .loc-trigger:disabled {
        opacity: 0.45;
        cursor: not-allowed;
    }
    .loc-trigger.has-value { color: var(--text-primary); }
    .loc-label { color: var(--text-muted); text-transform: lowercase; letter-spacing: 0.02em; }
    .loc-value {
        font-family: var(--font-mono);
        font-variant-numeric: tabular-nums;
        font-size: var(--fs-row);
        color: var(--text-primary);
    }
    .loc-empty { color: var(--text-faint); font-style: italic; }
    .chev {
        color: var(--text-faint);
        font-size: 10px;
        transform: translateY(-1px);
    }

    .pop {
        position: absolute;
        bottom: calc(100% + var(--s-2));
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        box-shadow: 0 16px 48px oklch(0 0 0 / 0.45);
        padding: var(--s-2);
        z-index: 50;
    }
    .pop-surah { left: 0; }
    .pop-ayah {
        left: 50%;
        transform: translateX(-50%);
        width: min(360px, calc(100vw - var(--s-4) * 2));
        display: flex;
        flex-direction: column;
        max-height: min(420px, 60vh);
    }

    .ayah-search {
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        color: var(--text-primary);
        padding: 6px var(--s-2);
        border-radius: var(--r-2);
        font-size: var(--fs-meta);
        outline: none;
        margin-bottom: var(--s-2);
    }
    .ayah-search:focus { border-color: var(--accent); }
    .ayah-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(44px, 1fr));
        gap: 4px;
        overflow-y: auto;
    }
    .ayah-cell {
        padding: 6px 0;
        background: transparent;
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        color: var(--text-secondary);
        font-family: var(--font-mono);
        font-variant-numeric: tabular-nums;
        font-size: var(--fs-meta);
        cursor: pointer;
        transition: border-color var(--t-fast), color var(--t-fast), background var(--t-fast);
    }
    .ayah-cell:hover {
        border-color: var(--border-strong);
        color: var(--text-primary);
        background: var(--panel-2);
    }
    .ayah-cell.active {
        border-color: var(--accent);
        color: var(--accent);
        background: var(--accent-tint);
    }
    .empty {
        grid-column: 1 / -1;
        padding: var(--s-3);
        text-align: center;
        color: var(--text-muted);
        font-size: var(--fs-meta);
    }

    /* ---------- Actions ---------- */
    .action {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px var(--s-2);
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        color: var(--text-primary);
        font: inherit;
        font-size: var(--fs-meta);
        cursor: pointer;
        transition: background var(--t-fast), border-color var(--t-fast), color var(--t-fast);
    }
    .action:hover:not(:disabled) {
        background: var(--panel);
        border-color: var(--border-strong);
    }
    .action:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    .action.ghost {
        background: transparent;
        color: var(--text-secondary);
    }
    .action.ghost:hover:not(:disabled) {
        background: var(--panel-2);
        color: var(--text-primary);
    }
    .action.ghost-accent {
        background: transparent;
        color: var(--accent);
        border-color: oklch(0.785 0.130 220 / 0.35);
    }
    .action.ghost-accent:hover:not(:disabled) {
        background: var(--accent-tint);
        border-color: var(--accent);
    }
    .action.primary {
        background: var(--accent);
        border-color: var(--accent);
        color: var(--accent-fg);
        font-weight: 500;
    }
    .action.primary:hover:not(:disabled) {
        background: var(--accent-strong);
        border-color: var(--accent-strong);
    }

    .action.save { min-width: 104px; justify-content: center; padding-inline: var(--s-3); }
    .action.save.saved {
        background: transparent;
        border-color: var(--border-quiet);
        color: var(--text-muted);
    }
    .save-glyph { color: oklch(0.78 0.13 155); font-weight: 600; }
    .action.save.auto-busy {
        background: transparent;
        border-color: oklch(0.785 0.130 220 / 0.35);
        color: var(--accent);
    }
    .save-pulse {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--accent);
        animation: pulse 1.4s ease-out-quart infinite;
    }
    @keyframes pulse {
        0%, 100% { opacity: 0.35; }
        50% { opacity: 1; }
    }

    /* Auto-save single-button toggle — quieter than Save, click to flip. */
    .autosave-toggle {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px var(--s-2);
        background: transparent;
        border: 1px dashed var(--border-quiet);
        border-radius: var(--r-2);
        color: var(--text-muted);
        cursor: pointer;
        font: inherit;
        font-size: var(--fs-meta);
        transition: color var(--t-fast), border-color var(--t-fast), background var(--t-fast);
    }
    .autosave-toggle:hover {
        color: var(--text-primary);
        border-color: var(--border-strong);
    }
    .autosave-toggle.on {
        border-style: solid;
        border-color: oklch(0.785 0.130 220 / 0.45);
        background: var(--accent-tint);
        color: var(--accent);
    }
    .autosave-glyph {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        opacity: 0.7;
    }
    .autosave-toggle.on .autosave-glyph { opacity: 1; }

    /* Utility (History) — icon + tiny label, ghostier than action buttons */
    .utility {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px var(--s-2);
        background: transparent;
        border: 1px solid transparent;
        border-radius: var(--r-2);
        color: var(--text-muted);
        cursor: pointer;
        font: inherit;
        font-size: var(--fs-meta);
        transition: color var(--t-fast), background var(--t-fast), border-color var(--t-fast);
    }
    .utility:hover {
        color: var(--text-primary);
        background: var(--panel-2);
        border-color: var(--border-quiet);
    }
    .utility.on {
        color: var(--accent);
        background: var(--accent-tint);
        border-color: oklch(0.785 0.130 220 / 0.35);
    }
    .util-glyph {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 16px;
        height: 16px;
    }

    /* ---------- Responsive ---------- */
    @media (max-width: 960px) {
        .segs-footer {
            flex-direction: column;
            align-items: stretch;
            gap: var(--s-2);
            padding: var(--s-2) var(--s-3);
        }
        /* Return location to in-flow stacking — absolute positioning would
           collapse it on top of the identity row at narrow widths. */
        .zone-location {
            position: static;
            transform: none;
            justify-content: flex-start;
        }
        .zone-save { justify-content: flex-start; }
        .pop-surah, .pop-ayah {
            left: 0;
            right: 0;
            transform: none;
            width: auto;
        }
    }
    @media (max-width: 540px) {
        .util-label { display: none; }
        .action.save { min-width: 92px; }
    }
</style>
