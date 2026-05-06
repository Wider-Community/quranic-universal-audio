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

    import { fetchJson } from '../../../../lib/api';
    import type { SegResolveRefResponse } from '../../../../lib/types/api';
    import type { Segment } from '../../../../lib/types/domain';
    import { segAllData } from '../../stores/chapter';
    import { setPendingOp } from '../../stores/dirty';
    import {
        clearEdit,
        pendingChainTarget,
    } from '../../stores/edit';
    import { _normalizeRef, formatRef, getVerseWordCounts } from '../../utils/data/references';
    import {
        commitRefEdit,
        consumePendingInitialSelection,
        consumePendingInitialValue,
    } from '../../utils/edit/reference';

    export let seg: Segment;

    const dispatch = createEventDispatcher<{
        preview: { text: string; ref: string } | null;
    }>();

    let inputEl: HTMLInputElement | undefined;
    let value = consumePendingInitialValue() ?? formatRef(seg.matched_ref, get(segAllData)?.verse_word_counts);
    let committed = false;
    let invalid = false;

    let fetchTimer: ReturnType<typeof setTimeout> | null = null;
    let lastFetchedValue = '';

    $: {
        const currentVal = value.trim();
        if (currentVal && currentVal !== lastFetchedValue) {
            if (fetchTimer) clearTimeout(fetchTimer);
            fetchTimer = setTimeout(() => {
                void fetchPreview(currentVal);
            }, 300);
        }
    }

    async function fetchPreview(candidate: string) {
        lastFetchedValue = candidate;
        const vwc = getVerseWordCounts();
        const normalized = _normalizeRef(candidate, vwc);
        if (!normalized) {
            dispatch('preview', null);
            return;
        }
        try {
            const data = await fetchJson<SegResolveRefResponse & { error?: string }>(
                `/api/seg/resolve_ref?ref=${encodeURIComponent(normalized)}`,
            );
            if (data.text && !data.error) {
                dispatch('preview', { text: data.display_text || data.text, ref: normalized });
            } else {
                dispatch('preview', null);
            }
        } catch (e) {
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
        pendingChainTarget.set(null);
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
        // After an invalid attempt, the input loses focus when we re-focus
        // immediately (browser quirks during async commit). Suppress the blur
        // auto-commit while invalid so the editor stays open for re-entry.
        if (invalid) return;
        void commit();
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
