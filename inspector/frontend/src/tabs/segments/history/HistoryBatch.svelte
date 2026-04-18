<script lang="ts">
    /**
     * HistoryBatch — one card for a single OpFlatItem in the history list.
     *
     * Dispatches across four item shapes:
     *   1. `strip-specials-card`  → "Deletion ×N" card with a single before
     *      snapshot + `(×N deleted)` placeholder.
     *   2. `multi-chapter-card`   → summary card listing touched chapters
     *      (no diff view).
     *   3. `revert-card`          → header-only badge marking the batch
     *      as Reverted.
     *   4. `op-card` (default)    → delegates to <HistoryOp> (handles both
     *      single and grouped ops).
     *
     * Header: op-type badge + follow-up badges, fix-kind chips, issue-delta
     * badges, "Reverted" badge, chapter name, formatted date, Undo/Discard.
     */

    import HistoryOp from './HistoryOp.svelte';
    import SegmentRow from '../list/SegmentRow.svelte';
    import { surahOptionText } from '../../../lib/utils/surah-info';
    import { EDIT_OP_LABELS } from '../../../lib/utils/segments/constants';
    import {
        onOpUndoClick,
        onPendingBatchDiscard,
    } from '../../../lib/utils/segments/undo';
    import {
        formatHistDate,
        SHORT_LABELS,
        snapToSeg,
        type HistorySnapshot,
        type OpFlatItem,
    } from '../../../lib/stores/segments/history';
    import { _deriveOpIssueDelta } from '../../../lib/utils/segments/classify';
    import type { EditOp } from '../../../lib/types/domain';

    // Props ------------------------------------------------------------------

    export let item: OpFlatItem;

    // Derived header bits ----------------------------------------------------

    $: group = item.group;
    $: primary = group[0];
    $: followUp = (() => {
        const m: Record<string, number> = {};
        for (let i = 1; i < group.length; i++) {
            const t = group[i]!.op_type;
            m[t] = (m[t] || 0) + 1;
        }
        return m;
    })();
    $: fixKinds = (() => {
        const set = new Set<string>();
        for (const op of group) {
            if (op.fix_kind && op.fix_kind !== 'manual') set.add(op.fix_kind);
        }
        if (item.type === 'strip-specials-card' || item.type === 'multi-chapter-card') {
            set.add('auto_fix');
        }
        return [...set];
    })();
    $: issueDelta = group.length > 0 ? _deriveOpIssueDelta(group) : { resolved: [], introduced: [] };

    // Strip-specials single-snapshot diff (shared "before" card + empty-after).
    $: stripSnap = item.type === 'strip-specials-card'
        ? ((group[0]?.targets_before?.[0]) as HistorySnapshot | undefined) ?? null
        : null;

    // Undo / discard handlers ------------------------------------------------
    function handleDiscardClick(e: MouseEvent): void {
        if (item.chapter == null) return;
        const btn = e.currentTarget as HTMLButtonElement;
        onPendingBatchDiscard(item.chapter, btn);
    }
    function handleUndoClick(e: MouseEvent): void {
        const bid = item.batchId;
        if (!bid) return;
        const btn = e.currentTarget as HTMLButtonElement;
        const opIds = (group as EditOp[]).map((op) => op.op_id);
        void onOpUndoClick(bid, opIds, btn);
    }
</script>

<div class="seg-history-batch" class:is-revert={item.isRevert}>
    <div class="seg-history-batch-header">
        {#if item.type === 'strip-specials-card'}
            <span class="seg-history-op-type-badge">Deletion &times;{group.length}</span>
        {:else if item.type === 'multi-chapter-card'}
            <span class="seg-history-op-type-badge">
                {EDIT_OP_LABELS[primary?.op_type ?? ''] || primary?.op_type || ''} &times;{group.length}
            </span>
        {:else if item.type === 'revert-card'}
            <!-- no op badge -->
        {:else if primary}
            <span class="seg-history-op-type-badge">
                {EDIT_OP_LABELS[primary.op_type] || primary.op_type}
            </span>
            {#each Object.entries(followUp) as [t, count]}
                <span class="seg-history-op-type-badge secondary">
                    + {EDIT_OP_LABELS[t] || t}{count > 1 ? ` \u00d7${count}` : ''}
                </span>
            {/each}
        {/if}

        {#each fixKinds as fk}
            <span class="seg-history-op-fix-kind">{fk}</span>
        {/each}

        {#if group.length > 0}
            {#each issueDelta.resolved as cat}
                <span class="seg-history-val-delta improved">&minus;{SHORT_LABELS[cat] || cat}</span>
            {/each}
            {#each issueDelta.introduced as cat}
                <span class="seg-history-val-delta regression">+{SHORT_LABELS[cat] || cat}</span>
            {/each}
        {/if}

        {#if item.isRevert}
            <span class="seg-history-batch-revert-badge">Reverted</span>
        {/if}

        {#if item.chapter != null}
            <span class="seg-history-batch-chapter">{surahOptionText(item.chapter)}</span>
        {/if}

        <span class="seg-history-batch-time">{formatHistDate(item.date || null)}</span>

        {#if item.isPending}
            <button
                class="btn btn-sm seg-history-undo-btn"
                on:click|stopPropagation={handleDiscardClick}
            >Discard</button>
        {:else if item.batchId && !item.isRevert}
            <button
                class="btn btn-sm seg-history-undo-btn"
                on:click|stopPropagation={handleUndoClick}
            >Undo</button>
        {/if}
    </div>

    {#if group.length > 0 || item.type === 'multi-chapter-card'}
        <div class="seg-history-batch-body">
            {#if item.type === 'strip-specials-card'}
                <!-- Deletion-group: one before card + (×N deleted) placeholder,
                     no arrow column (matches _renderSpecialDeleteGroup). -->
                <div class="seg-history-diff">
                    <div class="seg-history-before">
                        {#if stripSnap}
                            <SegmentRow
                                seg={snapToSeg(stripSnap, null)}
                                readOnly={true}
                                showPlayBtn={true}
                                mode="history"
                            />
                        {/if}
                    </div>
                    <div class="seg-history-after">
                        <div class="seg-history-empty">
                            {group.length > 1 ? `\u00d7${group.length} deleted` : '(deleted)'}
                        </div>
                    </div>
                </div>
            {:else if item.type === 'multi-chapter-card'}
                <div class="seg-history-chapter-list">
                    Chapters: {(item.chapters || []).map((c) => surahOptionText(c)).join(', ')}
                </div>
            {:else if group.length === 1 && primary}
                <HistoryOp
                    group={[primary]}
                    chapter={item.chapter}
                    batchId={item.batchId}
                    skipLabel={true}
                />
            {:else if group.length > 1}
                <HistoryOp
                    group={group}
                    chapter={item.chapter}
                    batchId={item.batchId}
                    skipLabel={true}
                />
            {/if}
        </div>
    {/if}
</div>
