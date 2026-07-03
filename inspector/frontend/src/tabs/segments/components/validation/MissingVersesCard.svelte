<script lang="ts">
    import { createEventDispatcher } from 'svelte';

    import { localeStore, tr } from '../../../../lib/i18n/locale-store';
    import * as m from '../../../../lib/paraglide/messages';
    import type { SegValMissingVerseItem } from '../../../../lib/types/generated/schemas';
    import type { Segment } from '../../../../lib/types/view-models';
    import { getAdjacentSegments, segAllData } from '../../stores/chapter';
    import { findMissingVerseBoundarySegments } from '../../utils/validation/missing-verse-context';
    import SegmentRow from '../list/SegmentRow.svelte';

    const dispatch = createEventDispatcher<{ contextchange: boolean }>();

    // ---- Props ----
    export let item: SegValMissingVerseItem;

    // ---- State ----
    let showContext = false;

    // ---- Derived ----
    // Subscribes to segAllData so boundary re-derives after split/merge
    // mutates seg indices in the chapter.
    $: segStoreTick = $segAllData;
    $: boundary = (void segStoreTick, findMissingVerseBoundarySegments(item.chapter, item.verse_key));
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

    // Ordered sibling list — render order — passed to each SegmentRow so
    // playback prefetch can warm the next sibling's clip URL by list
    // position. Mirrors the template below exactly.
    $: siblings = ((): Segment[] => {
        const out: Segment[] = [];
        if (beforeCtx) out.push(beforeCtx);
        if (prev) out.push(prev);
        if (nextDifferent && next) out.push(next);
        if (afterCtx) out.push(afterCtx);
        return out;
    })();

    // ---- Public interface (forwarded from ErrorCard dispatcher) ----
    export function getIsContextShown(): boolean { return showContext; }
    export function showContextForced(): void { showContext = true; dispatch('contextchange', true); }
    export function hideContextForced(): void { showContext = false; dispatch('contextchange', false); }

    function toggleContext(): void {
        showContext = !showContext;
        dispatch('contextchange', showContext);
    }

    $: beforeLabel = tr($localeStore, m.segments_validation_context_label_before());
    $: prevBoundaryLabel = tr($localeStore, m.segments_validation_context_label_previous_verse_boundary());
    $: nextBoundaryLabel = tr($localeStore, m.segments_validation_context_label_next_verse_boundary());
    $: afterLabel = tr($localeStore, m.segments_validation_context_label_after());
    $: noBoundarySegsLabel = tr($localeStore, m.segments_validation_no_boundary_segments());
    $: contextToggleLabel = tr($localeStore, showContext ? m.segments_validation_hide_context_button() : m.segments_validation_show_context_button());
</script>

<div class="val-card-issue-label">
    {item.msg ? `${item.verse_key} \u2014 ${item.msg}` : item.verse_key}
</div>
{#if beforeCtx}
    <SegmentRow
        seg={beforeCtx}
        isContext={true}
        contextLabel={beforeLabel}
        showPlayBtn={true}
        showChapter={true}
        accordionSiblings={siblings}
    />
{/if}
{#if prev}
    <SegmentRow
        seg={prev}
        isContext={true}
        contextLabel={prevBoundaryLabel}
        showPlayBtn={true}
        showChapter={true}
        accordionSiblings={siblings}
    />
{/if}
{#if nextDifferent && next}
    <SegmentRow
        seg={next}
        isContext={true}
        contextLabel={nextBoundaryLabel}
        showPlayBtn={true}
        showChapter={true}
        accordionSiblings={siblings}
    />
{/if}
{#if afterCtx}
    <SegmentRow
        seg={afterCtx}
        isContext={true}
        contextLabel={afterLabel}
        showPlayBtn={true}
        showChapter={true}
        accordionSiblings={siblings}
    />
{/if}
{#if !hasBoundarySegs}
    <div class="seg-loading">{noBoundarySegsLabel}</div>
{:else}
    <div class="val-card-actions">
        <button
            class="val-action-btn val-action-btn-muted val-ctx-toggle-btn"
            on:click={toggleContext}
        >{contextToggleLabel}</button>
    </div>
{/if}
