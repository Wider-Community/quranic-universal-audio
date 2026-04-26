<script lang="ts">
    /**
     * HistoryOp — unified single + grouped operation diff row.
     *
     * Renders an op-type label row with fix-kind badges + Undo button, a
     * two-column diff (`.seg-history-before` / `.seg-history-arrows` /
     * `.seg-history-after`) with `<SegmentRow mode="history">` cards, and
     * the `<HistoryArrows>` column driven by bound card refs. Length-1
     * groups degrade cleanly to a single pair of cards.
     */

    import { tick } from 'svelte';

    import SegmentRow from '../list/SegmentRow.svelte';
    import HistoryArrows from './HistoryArrows.svelte';
    import { EDIT_OP_LABELS } from '../../utils/constants';
    import { onOpUndoClick } from '../../utils/save/undo';
    import {
        snapToSeg,
        type HistorySnapshot,
    } from '../../stores/history';
    import type { MergeHighlight, TrimHighlight } from '../../types/segments-waveform';
    import type { EditOp } from '../../../../lib/types/domain';

    // Props ------------------------------------------------------------------

    export let group: EditOp[];
    export let chapter: number | null = null;
    export let batchId: string | null = null;
    export let skipLabel: boolean = false;

    // Derived diff inputs ----------------------------------------------------

    $: primary = group[0]!;
    $: isGroup = group.length > 1;

    $: diff = computeDiff(group, isGroup, primary);

    function computeDiff(g: EditOp[], grouped: boolean, prim: EditOp) {
        const before = ((prim?.targets_before || []) as HistorySnapshot[]);
        if (!grouped) {
            return { before, after: (prim?.targets_after || []) as HistorySnapshot[] };
        }
        const finalSnaps = new Map<string, HistorySnapshot>();
        for (const op of g) {
            for (const s of (op.targets_after || []) as HistorySnapshot[]) {
                if (s.segment_uid) finalSnaps.set(s.segment_uid, s);
            }
        }
        const primaryAfterUids = ((prim?.targets_after || []) as HistorySnapshot[]).map((t) => t.segment_uid);
        const after = primaryAfterUids
            .map((uid) => (uid ? finalSnaps.get(uid) : undefined))
            .filter((s): s is HistorySnapshot => !!s);
        return { before, after };
    }

    $: followUp = (() => {
        const m: Record<string, number> = {};
        if (!isGroup) return m;
        for (let i = 1; i < group.length; i++) {
            const t = group[i]!.op_type;
            m[t] = (m[t] || 0) + 1;
        }
        return m;
    })();

    $: fixKinds = (() => {
        const set = new Set<string>();
        if (isGroup) {
            for (const op of group) {
                if (op.fix_kind && op.fix_kind !== 'manual') set.add(op.fix_kind);
            }
        } else if (primary?.fix_kind && primary.fix_kind !== 'manual') {
            set.add(primary.fix_kind);
        }
        return [...set];
    })();

    // 1→1 change highlight derivations (match _highlightChanges verbatim).
    $: isOneToOne = diff.before.length === 1 && diff.after.length === 1;
    $: trimHighlights = (() => {
        if (!isOneToOne) return { before: null, after: null };
        const b = diff.before[0]!;
        const a = diff.after[0]!;
        if (b.time_start === a.time_start && b.time_end === a.time_end) {
            return { before: null, after: null };
        }
        const beforeHL: TrimHighlight = { color: 'red', otherStart: a.time_start, otherEnd: a.time_end };
        const afterHL: TrimHighlight = { color: 'green', otherStart: b.time_start, otherEnd: b.time_end };
        return { before: beforeHL, after: afterHL };
    })();
    $: afterChangedFields = (() => {
        if (!isOneToOne) return null;
        const b = diff.before[0]!;
        const a = diff.after[0]!;
        const set = new Set<'ref' | 'duration' | 'conf' | 'body'>();
        if (b.matched_ref !== a.matched_ref) set.add('ref');
        if (b.time_start !== a.time_start || b.time_end !== a.time_end) set.add('duration');
        if (b.confidence !== a.confidence) set.add('conf');
        if (b.matched_text !== a.matched_text) set.add('body');
        return set.size > 0 ? set : null;
    })();

    // 2→1 merge highlight on result card.
    $: mergeAfterHL = (() => {
        if (!primary) return null;
        const mergeLike = primary.op_type === 'merge_segments' || primary.op_type === 'waqf_sakt';
        if (!mergeLike) return null;
        if (diff.before.length !== 2 || diff.after.length !== 1) return null;
        if (!primary.merge_direction) return null;
        const hlSnap = primary.merge_direction === 'prev' ? diff.before[1]! : diff.before[0]!;
        const hl: MergeHighlight = { hlStart: hlSnap.time_start, hlEnd: hlSnap.time_end };
        return hl;
    })();

    function handleOpUndoClick(e: MouseEvent): void {
        if (!batchId) return;
        const btn = e.currentTarget as HTMLButtonElement;
        void onOpUndoClick(batchId, group.map((op) => op.op_id), btn);
    }

    // Bound card refs driving HistoryArrows ---------------------------------
    let beforeCardEls: (HTMLElement | undefined)[] = [];
    let afterCardEls: (HTMLElement | undefined)[] = [];
    let emptyEl: HTMLElement | null = null;

    // After each render cycle, regroup non-null refs into arrays that
    // HistoryArrows measures. A tick ensures <SegmentRow> children have
    // committed their DOM by the time we read the wrappers.
    let arrowsBefore: HTMLElement[] = [];
    let arrowsAfter: HTMLElement[] = [];
    $: void (async () => {
        void diff;
        await tick();
        arrowsBefore = beforeCardEls.filter((e): e is HTMLElement => !!e);
        arrowsAfter = afterCardEls.filter((e): e is HTMLElement => !!e);
    })();
</script>

<div class="seg-history-op" class:seg-history-grouped-op={isGroup}>
    {#if !skipLabel}
        <div class="seg-history-op-label">
            {#if primary}
                <span class="seg-history-op-type-badge">
                    {EDIT_OP_LABELS[primary.op_type] || primary.op_type}
                </span>
            {/if}
            {#each Object.entries(followUp) as [t, count]}
                <span class="seg-history-op-type-badge secondary">
                    + {EDIT_OP_LABELS[t] || t}{count > 1 ? ` \u00d7${count}` : ''}
                </span>
            {/each}
            {#each fixKinds as fk}
                <span class="seg-history-op-fix-kind">{fk}</span>
            {/each}
            {#if batchId}
                <button
                    class="btn btn-sm seg-history-op-undo-btn"
                    on:click|stopPropagation={handleOpUndoClick}
                >Undo</button>
            {/if}
        </div>
    {/if}

    <div class="seg-history-diff">
        <div class="seg-history-before">
            {#each diff.before as snap, i (snap.segment_uid ?? i)}
                <div bind:this={beforeCardEls[i]}>
                    <SegmentRow
                        seg={snapToSeg(snap, chapter)}
                        readOnly={true}
                        showChapter={true}
                        showPlayBtn={true}
                        mode="history"
                        instanceRole="history"
                        trimHL={i === 0 ? trimHighlights.before : null}
                    />
                </div>
            {/each}
        </div>

        <div class="seg-history-arrows">
            <HistoryArrows
                beforeCards={arrowsBefore}
                afterCards={arrowsAfter}
                {emptyEl}
            />
        </div>

        <div class="seg-history-after">
            {#if diff.after.length === 0}
                <div class="seg-history-empty" bind:this={emptyEl}>(deleted)</div>
            {:else}
                {#each diff.after as snap, i (snap.segment_uid ?? i)}
                    <div bind:this={afterCardEls[i]}>
                        <SegmentRow
                            seg={snapToSeg(snap, chapter)}
                            readOnly={true}
                            showChapter={true}
                            showPlayBtn={true}
                            mode="history"
                            instanceRole="history"
                            trimHL={isOneToOne && i === 0 ? trimHighlights.after : null}
                            mergeHL={i === 0 ? mergeAfterHL : null}
                            changedFields={isOneToOne && i === 0 ? afterChangedFields : null}
                        />
                    </div>
                {/each}
            {/if}
        </div>
    </div>
</div>
