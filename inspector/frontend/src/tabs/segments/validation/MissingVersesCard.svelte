<script lang="ts">
    import { onMount, onDestroy } from 'svelte';

    import { getAdjacentSegments } from '../../../lib/stores/segments/chapter';
    import { findMissingVerseBoundarySegments } from '../../../lib/utils/segments/missing-verse-context';
    import { state } from '../../../segments/state';
    import { injectCard } from '../../../lib/utils/validation-card-inject';
    import type { SegValMissingVerseItem } from '../../../types/domain';

    // ---- Props ----
    export let item: SegValMissingVerseItem;

    // ---- DOM refs ----
    let cardsContainerEl: HTMLElement;

    // ---- State ----
    let showContext = false;
    let contextEls: HTMLElement[] = [];
    let hasBoundarySegs = false;

    $: ctxMode = state._accordionContext?.['missing_verses'] ?? 'hidden';

    // ---- Public interface (forwarded from ErrorCard dispatcher) ----
    export function getIsContextShown(): boolean { return showContext; }
    export function showContextForced(): void {
        if (!showContext) { _doShowContext(); showContext = true; }
    }
    export function hideContextForced(): void {
        if (showContext) { _hideContext(); showContext = false; }
    }

    // ---- Context toggle ----
    function toggleContext(): void {
        if (showContext) { _hideContext(); showContext = false; }
        else { _doShowContext(); showContext = true; }
    }

    function _doShowContext(): void {
        if (!cardsContainerEl) return;
        const { prev, next } = findMissingVerseBoundarySegments(item.chapter, item.verse_key);
        if (prev && prev.chapter != null) {
            const { prev: pp } = getAdjacentSegments(prev.chapter, prev.index);
            const firstCard = cardsContainerEl.querySelector<HTMLElement>('.seg-row');
            if (pp) contextEls.push(injectCard(cardsContainerEl, pp, { isContext: true, contextLabel: 'Before' }, firstCard ?? null));
        }
        if (next && next.chapter != null) {
            const { next: nn } = getAdjacentSegments(next.chapter, next.index);
            if (nn) contextEls.push(injectCard(cardsContainerEl, nn, { isContext: true, contextLabel: 'After' }));
        }
    }

    function _hideContext(): void {
        contextEls.forEach((el) => el.remove());
        contextEls = [];
    }

    // ---- Mount ----
    onMount(() => {
        if (!cardsContainerEl) return;
        const { prev, next } = findMissingVerseBoundarySegments(item.chapter, item.verse_key);
        const nextDifferent = next != null && (!prev || next.index !== prev.index);
        hasBoundarySegs = prev != null || nextDifferent;
        if (prev) injectCard(cardsContainerEl, prev, { contextLabel: 'Previous verse boundary', readOnly: true });
        if (nextDifferent && next) injectCard(cardsContainerEl, next, { contextLabel: 'Next verse boundary', readOnly: true });
    });

    onDestroy(() => { _hideContext(); });
</script>

<div class="val-card-issue-label">
    {item.msg ? `${item.verse_key} \u2014 ${item.msg}` : item.verse_key}
</div>
<div bind:this={cardsContainerEl}></div>
{#if !hasBoundarySegs}
    <div class="seg-loading">No boundary segments found for this missing verse.</div>
{:else}
    <div class="val-card-actions">
        <button
            class="val-action-btn val-action-btn-muted val-ctx-toggle-btn"
            on:click={toggleContext}
        >{showContext ? 'Hide Context' : 'Show Context'}</button>
    </div>
{/if}
