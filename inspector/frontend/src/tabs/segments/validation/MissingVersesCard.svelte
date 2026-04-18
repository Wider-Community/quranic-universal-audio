<script lang="ts">
    import { getAdjacentSegments } from '../../../lib/stores/segments/chapter';
    import { findMissingVerseBoundarySegments } from '../../../lib/utils/segments/missing-verse-context';
    import type { SegValMissingVerseItem, Segment } from '../../../types/domain';
    import SegmentRow from '../SegmentRow.svelte';

    // ---- Props ----
    export let item: SegValMissingVerseItem;

    // ---- State ----
    let showContext = false;

    // ---- Derived ----
    $: boundary = findMissingVerseBoundarySegments(item.chapter, item.verse_key);
    $: prev = boundary.prev;
    $: next = boundary.next;
    $: nextDifferent = next != null && (!prev || next.index !== prev.index);
    $: hasBoundarySegs = prev != null || nextDifferent;

    $: beforeCtx = ((): Segment | null => {
        if (!showContext || !prev || prev.chapter == null) return null;
        return getAdjacentSegments(prev.chapter, prev.index).prev;
    })();

    $: afterCtx = ((): Segment | null => {
        if (!showContext || !next || next.chapter == null) return null;
        return getAdjacentSegments(next.chapter, next.index).next;
    })();

    // ---- Public interface (forwarded from ErrorCard dispatcher) ----
    export function getIsContextShown(): boolean { return showContext; }
    export function showContextForced(): void { showContext = true; }
    export function hideContextForced(): void { showContext = false; }

    function toggleContext(): void {
        showContext = !showContext;
    }
</script>

<div class="val-card-issue-label">
    {item.msg ? `${item.verse_key} \u2014 ${item.msg}` : item.verse_key}
</div>
{#if beforeCtx}
    <SegmentRow
        seg={beforeCtx}
        isContext={true}
        contextLabel="Before"
        showPlayBtn={true}
        showChapter={true}
    />
{/if}
{#if prev}
    <SegmentRow
        seg={prev}
        readOnly={true}
        contextLabel="Previous verse boundary"
        showPlayBtn={true}
        showChapter={true}
    />
{/if}
{#if nextDifferent && next}
    <SegmentRow
        seg={next}
        readOnly={true}
        contextLabel="Next verse boundary"
        showPlayBtn={true}
        showChapter={true}
    />
{/if}
{#if afterCtx}
    <SegmentRow
        seg={afterCtx}
        isContext={true}
        contextLabel="After"
        showPlayBtn={true}
        showChapter={true}
    />
{/if}
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
