<script lang="ts">
    /**
     * WaslBoundary — always-shown WASL/WAQF picker rendered between adjacent
     * pieces inside a cross-verse accordion card's split-group.
     *
     * Both labels are always visible. Three states:
     *
     *   pending  (leftUid ∈ pendingWaslConfirm, no prior pick):
     *       both labels muted; picker auto-scrolls + focuses when
     *       focusWaslBoundary names this UID. Chain is paused here.
     *
     *   wasl    (leftSeg.is_wasl === true):
     *       WASL in accent, WAQF muted-clickable. User can switch any time.
     *
     *   waqf    (leftSeg.is_wasl === false and NOT pending):
     *       WAQF in accent, WASL muted-clickable.
     *
     * Commit branch:
     *   • If a pending split op for this seg exists in the dirty buffer,
     *     amend the split op's snapshots in place via amendSegInOp — no
     *     new ``set_is_wasl`` op emitted. Keeps the history-row count = 1
     *     per logical split regardless of how many wasl decisions or
     *     mind-changes happen during the chain.
     *   • Otherwise (post-save ad-hoc edit), dispatch a ``set_is_wasl``
     *     op via the standard setIsWaslOnSegment dispatcher.
     *
     * After commit, the picker clears its UID from pendingWaslConfirm,
     * unhooks focus, and calls resumePendingChain() so the post-split
     * chain advances to the next piece's ref-edit.
     */

    import { tick } from 'svelte';

    import { editGate } from '../../../../lib/actions/editGate';
    import type { EditOp, Segment } from '../../../../lib/types/domain';
    import { refreshSegInStore } from '../../stores/chapter';
    import {
        amendSegInOp,
        getChapterOps,
        markDirty,
    } from '../../stores/dirty';
    import {
        clearWaslPending,
        focusWaslBoundary,
        pendingWaslConfirm,
    } from '../../stores/edit';
    import { resumePendingChain } from '../../utils/edit/reference';
    import { setIsWaslOnSegment } from '../../utils/edit/setIsWasl';

    export let leftSeg: Segment;
    export let rightSeg: Segment;

    let waslBtnEl: HTMLButtonElement | undefined;

    $: leftUid = leftSeg.segment_uid ?? '';
    $: sameChapter =
        leftSeg.chapter != null
        && rightSeg.chapter != null
        && leftSeg.chapter === rightSeg.chapter;

    $: isWasl = leftSeg.is_wasl === true;
    $: isPending = leftUid !== '' && $pendingWaslConfirm.has(leftUid);

    // Reactive auto-focus when the chain pauses on this boundary.
    // Defer to next tick so the smooth-scroll lands before the focus ring
    // appears; otherwise the user sees the ring mid-scroll and may miss it.
    $: if (leftUid && $focusWaslBoundary === leftUid && waslBtnEl) {
        const el = waslBtnEl;
        el.scrollIntoView({ block: 'center', behavior: 'smooth' });
        void tick().then(() => el.focus());
    }

    function commit(value: boolean): void {
        if (!leftUid || leftSeg.chapter == null) return;
        const chapter = leftSeg.chapter;

        try {
            const parentSplit = _findPendingSplitFor(chapter, leftUid);
            if (parentSplit) {
                // While the parent split is still in the dirty buffer,
                // amend its targets_after snapshots in place. No new op,
                // no history-row noise from mind-changes during the chain.
                amendSegInOp(parentSplit, leftUid, { is_wasl: value });
                leftSeg.is_wasl = value;
                delete (leftSeg as Segment & { _derived?: unknown })._derived;
                refreshSegInStore(leftSeg);
                markDirty(chapter, leftSeg.index);
            } else if (value !== isWasl) {
                // Post-save ad-hoc edit: emit a real set_is_wasl op.
                setIsWaslOnSegment(leftSeg, value);
            }
        } catch (err) {
            console.warn('WaslBoundary: commit failed:', err);
        } finally {
            clearWaslPending(leftUid);
            focusWaslBoundary.set(null);
            // Re-enter the chain handoff. If a pending wasl gate was the
            // only thing blocking this entry, it now clears and the
            // chain pops + advances to the next ref-edit.
            resumePendingChain();
        }
    }

    function _findPendingSplitFor(chapter: number, uid: string): EditOp | null {
        for (const op of getChapterOps(chapter)) {
            if (op.op_type !== 'split_segment') continue;
            const after = op.targets_after as
                | Array<{ segment_uid?: string }>
                | undefined;
            if (!Array.isArray(after)) continue;
            if (after.some((t) => t.segment_uid === uid)) return op;
        }
        return null;
    }
</script>

{#if sameChapter && leftUid}
    <div
        class="wasl-boundary"
        class:is-pending={isPending}
        class:is-wasl={!isPending && isWasl}
        class:is-waqf={!isPending && !isWasl}
        role="group"
        aria-label="Boundary annotation: wasl or waqf"
    >
        <span class="rule" aria-hidden="true"></span>
        <span class="picker">
            <button
                bind:this={waslBtnEl}
                type="button"
                class="choice"
                class:active={!isPending && isWasl}
                aria-pressed={!isPending && isWasl}
                title="Wasl — continuous recitation across this boundary"
                use:editGate
                on:click={() => commit(true)}
            >WASL</button>
            <span class="sep" aria-hidden="true">·</span>
            <button
                type="button"
                class="choice"
                class:active={!isPending && !isWasl}
                aria-pressed={!isPending && !isWasl}
                title="Waqf — the reciter stopped at this boundary"
                use:editGate
                on:click={() => commit(false)}
            >WAQF</button>
        </span>
        <span class="rule" aria-hidden="true"></span>
    </div>
{/if}

<style>
    .wasl-boundary {
        display: flex;
        align-items: center;
        gap: var(--s-3);
        padding: var(--s-2) var(--s-3);
    }

    .rule {
        flex: 1 1 auto;
        height: 0;
        border-top: 1px solid var(--border-quiet);
        transition: border-color var(--t-fast) var(--ease-out-quart);
    }
    .is-pending .rule {
        border-top-color: var(--accent-tint);
    }
    .is-wasl .rule,
    .is-waqf .rule {
        border-top-color: var(--border-default);
    }

    .picker {
        display: inline-flex;
        align-items: baseline;
        gap: var(--s-2);
        padding: 2px 8px;
        border-radius: var(--r-1);
        font-family: var(--font-sans);
        font-size: var(--fs-meta);
        line-height: var(--lh-tight);
        letter-spacing: 0.12em;
        font-weight: 500;
        transition:
            background var(--t-fast) var(--ease-out-quart),
            box-shadow var(--t-fast) var(--ease-out-quart);
    }
    .is-pending .picker {
        background: var(--accent-tint-soft);
        box-shadow: 0 0 0 1px var(--accent-tint);
    }

    .choice {
        background: transparent;
        border: 0;
        padding: 0;
        cursor: pointer;
        color: var(--text-muted);
        font: inherit;
        letter-spacing: inherit;
        transition: color var(--t-fast) var(--ease-out-quart);
    }
    .choice:hover {
        color: var(--text-primary);
    }
    .choice.active {
        color: var(--accent);
    }
    .choice.active:hover {
        color: var(--accent-strong);
    }
    .choice:focus-visible {
        outline: 2px solid var(--accent);
        outline-offset: 3px;
        border-radius: var(--r-1);
    }

    .sep {
        color: var(--text-faint);
    }
</style>
