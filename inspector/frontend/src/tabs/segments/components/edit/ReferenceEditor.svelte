<script lang="ts">
    /**
     * ReferenceEditor — inline Svelte input for reference-edit mode.
     *
     * Mounted by SegmentRow.svelte in place of the `.seg-text-ref` span when
     * the row is the current reference-edit target (`isEditingThisRow &&
     * $editMode === 'reference'`). Owns its local input value; on Enter or
     * blur it calls `commitRefEdit`; on Escape it calls `exitEditMode` to
     * restore the span (the old `matched_ref` renders reactively).
     *
     * On invalid commit (malformed / unknown_verse / resolve_failed) the input
     * goes red, stays focused, and the `committed` latch resets so the user
     * can retry. On the next keystroke the red state clears.
     */

    import { createEventDispatcher,onMount } from 'svelte';
    import { get } from 'svelte/store';

    import { quranRefs } from '../../../../lib/refs/quran-refs';
    import type { Segment } from '../../../../lib/types/domain';
    import { setPendingOp } from '../../stores/dirty';
    import {
        clearEdit,
        pendingChainTargets,
        pendingWaslConfirm,
    } from '../../stores/edit';
    import {
        _normalizeRef,
        dkTextForRef,
        formatRef,
        getVerseWordCounts,
    } from '../../utils/data/references';
    import {
        commitRefEdit,
        consumePendingInitialSelection,
        consumePendingInitialValue,
    } from '../../utils/edit/reference';

    export let seg: Segment;

    const dispatch = createEventDispatcher<{
        preview: { ref: string } | null;
    }>();

    let inputEl: HTMLInputElement | undefined;
    let value = consumePendingInitialValue() ?? formatRef(seg.matched_ref, get(quranRefs)?.verse_word_counts);
    let committed = false;
    let invalid = false;

    // Recompute the live preview synchronously on every keystroke. The
    // SegmentRow body re-derives its text from `previewState.ref` via the
    // same `dkTextForRef` helper, so we only signal validity here — the
    // resolved text never crosses the boundary.
    $: {
        const currentVal = value.trim();
        const vwc = getVerseWordCounts();
        const normalized = _normalizeRef(currentVal, vwc);
        const dk = $quranRefs?.dk_words;
        if (normalized && dkTextForRef(normalized, dk, vwc)) {
            dispatch('preview', { ref: normalized });
        } else {
            dispatch('preview', null);
        }
    }

    onMount(() => {
        inputEl?.focus();
        const sel = consumePendingInitialSelection();
        if (sel && inputEl) {
            // Chain-mounted: place cursor at the dash boundary. Selecting from
            // `from` to value.length lets the user type the new end portion
            // and have it replace the highlighted suffix.
            inputEl.setSelectionRange(sel.from, sel.to);
        } else {
            inputEl?.select();
        }
    });

    async function commit(): Promise<void> {
        if (committed) return;
        committed = true;
        const result = await commitRefEdit(seg, value.trim());
        if (result.status === 'invalid') {
            // Don't latch `committed` — let the user retry. Re-focus and select
            // so the next keystroke replaces the invalid value, while the red
            // border signals the rejection.
            committed = false;
            invalid = true;
            inputEl?.focus();
            inputEl?.select();
            return;
        }
    }

    function cancel(): void {
        if (committed) return;
        committed = true;
        setPendingOp(null);
        // Cancelling one ref edit aborts the full split-chain — user can
        // Edit Ref manually on the remaining pieces. Clearing the whole
        // queue prevents a stale handoff fire when the next clearEdit lands.
        // Also drop any wasl-pending UIDs the chain would have prompted for,
        // otherwise their pickers stay stuck in the muted "awaiting" state
        // even though no chain will revisit them.
        pendingChainTargets.set([]);
        pendingWaslConfirm.set(new Set());
        clearEdit();
        dispatch('preview', null);
    }

    function onKeydown(e: KeyboardEvent): void {
        e.stopPropagation();
        if (e.key === 'Enter') {
            e.preventDefault();
            void commit();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            cancel();
        }
    }

    function onInput(): void {
        if (invalid) invalid = false;
    }

    function onBlur(): void {
        // Click-away = cancel (parity with Escape). Only Enter commits, so a
        // stray click outside the input never bumps confidence to 1.0 via the
        // unchanged-ref audit path. Skip while invalid so the editor stays
        // open after a rejected attempt (browser re-focus quirk).
        if (invalid) return;
        cancel();
    }

    function onClick(e: MouseEvent): void {
        e.stopPropagation();
    }
</script>

<input
    bind:this={inputEl}
    bind:value
    type="text"
    class="seg-text-ref-input"
    class:invalid
    on:keydown={onKeydown}
    on:input={onInput}
    on:blur={onBlur}
    on:click={onClick}
/>
