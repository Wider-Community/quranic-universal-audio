<script lang="ts">
    /**
     * ErrorCard — dispatcher that selects the appropriate card subcomponent
     * based on the validation category.
     *
     * Public 3-method API (getIsContextShown / showContextForced /
     * hideContextForced) is forwarded to the active child via bind:this so
     * ValidationPanel's "Show All Context" feature keeps working identically.
     */

    import GenericIssueCard from './GenericIssueCard.svelte';
    import MissingVersesCard from './MissingVersesCard.svelte';
    import MissingWordsCard from './MissingWordsCard.svelte';
    import type {
        SegValAnyItem,
        SegValMissingVerseItem,
        SegValMissingWordsItem,
    } from '../../../types/domain';

    // ---- Props ----
    export let category: string;
    export let item: SegValAnyItem;

    // ---- Child refs for API forwarding ----
    let mwCard: MissingWordsCard;
    let mvCard: MissingVersesCard;
    let genCard: GenericIssueCard;

    // Type-narrowed item props for each branch (avoids `as` casts in template).
    $: mwItem = item as SegValMissingWordsItem;
    $: mvItem = item as SegValMissingVerseItem;

    function _active(): { getIsContextShown(): boolean; showContextForced(): void; hideContextForced(): void } | null {
        if (category === 'missing_words') return mwCard ?? null;
        if (category === 'missing_verses') return mvCard ?? null;
        return genCard ?? null;
    }

    // ---- Public interface ----
    export function getIsContextShown(): boolean {
        return _active()?.getIsContextShown() ?? false;
    }
    export function showContextForced(): void {
        _active()?.showContextForced();
    }
    export function hideContextForced(): void {
        _active()?.hideContextForced();
    }
</script>

<div class="val-card-wrapper">
    {#if category === 'missing_words'}
        <MissingWordsCard
            bind:this={mwCard}
            item={mwItem}
        />
    {:else if category === 'missing_verses'}
        <MissingVersesCard
            bind:this={mvCard}
            item={mvItem}
        />
    {:else}
        <GenericIssueCard
            bind:this={genCard}
            {category}
            {item}
        />
    {/if}
</div>

<style>
    .val-card-wrapper {
        margin-bottom: 8px;
        padding: 6px 8px;
        background: #0f0f23;
        border: 1px solid #2a2a4a;
        border-radius: 4px;
    }
</style>
