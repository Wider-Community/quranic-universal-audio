<script lang="ts">
    /**
     * ReferenceEditor — inline Svelte input for reference-edit mode.
     *
     * Mounted by SegmentRow.svelte in place of the `.seg-text-ref` span when
     * the row is the current reference-edit target (`isEditingThisRow &&
     * $editMode === 'reference'`). Owns its local input value; on Enter or
     * blur it calls `commitRefEdit`; on Escape it calls `exitEditMode` to
     * restore the span (the old `matched_ref` renders reactively).
     */

    import { get } from 'svelte/store';
    import { onMount } from 'svelte';

    import { segAllData } from '../../../lib/stores/segments/chapter';
    import { setPendingOp } from '../../../lib/stores/segments/dirty';
    import {
        clearEdit,
        splitChainCategory,
        splitChainUid,
    } from '../../../lib/stores/segments/edit';
    import { commitRefEdit } from '../../../lib/utils/segments/edit-reference';
    import { formatRef } from '../../../lib/utils/segments/references';
    import type { Segment } from '../../../types/domain';

    export let seg: Segment;

    let inputEl: HTMLInputElement | undefined;
    let value = formatRef(seg.matched_ref, get(segAllData)?.verse_word_counts);
    let committed = false;

    onMount(() => {
        inputEl?.focus();
        inputEl?.select();
    });

    function commit(): void {
        if (committed) return;
        committed = true;
        void commitRefEdit(seg, value.trim());
    }

    function cancel(): void {
        if (committed) return;
        committed = true;
        setPendingOp(null);
        splitChainUid.set(null);
        splitChainCategory.set(null);
        clearEdit();
    }

    function onKeydown(e: KeyboardEvent): void {
        e.stopPropagation();
        if (e.key === 'Enter') {
            e.preventDefault();
            commit();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            cancel();
        }
    }

    function onBlur(): void {
        commit();
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
    on:keydown={onKeydown}
    on:blur={onBlur}
    on:click={onClick}
/>
