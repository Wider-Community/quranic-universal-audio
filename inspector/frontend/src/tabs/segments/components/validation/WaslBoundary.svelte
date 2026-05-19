<script lang="ts">
    /**
     * WaslBoundary — inline typographic marker for a wasl boundary inside
     * a cross-verse accordion card's split-group. Three states, no chip:
     *
     *  • prompting (leftSeg.uid in pendingWaslConfirm, not yet committed yes):
     *      ── waṣl?  no · yes ──
     *
     *  • committed yes (leftSeg.is_wasl === true):
     *      ── waṣl ──
     *
     *  • default / committed no (otherwise):
     *      ──────────  (hairline; hover reveals an "edit" affordance)
     *
     * Rendered between adjacent same-chapter pieces in
     * GenericIssueCard.svelte's mainMembers loop, ONLY when the card's
     * category is "cross_verse". Not slotted globally in the segment list.
     *
     * Click commits ``setIsWasl(true|false)`` via the standard dispatcher;
     * the chain advances normally without a modal.
     */

    import type { Segment } from '../../../../lib/types/domain';
    import { editGate } from '../../../../lib/actions/editGate';
    import {
        clearWaslPending,
        pendingWaslConfirm,
    } from '../../stores/edit';
    import { setIsWaslOnSegment } from '../../utils/edit/setIsWasl';

    export let leftSeg: Segment;
    export let rightSeg: Segment;

    let hovering = false;

    $: leftUid = leftSeg.segment_uid ?? '';
    $: sameChapter =
        leftSeg.chapter != null
        && rightSeg.chapter != null
        && leftSeg.chapter === rightSeg.chapter;

    $: isCommittedYes = leftSeg.is_wasl === true;
    $: isPending = leftUid !== '' && $pendingWaslConfirm.has(leftUid) && !isCommittedYes;

    function commit(value: boolean): void {
        if (!leftUid) return;
        try {
            if (value === isCommittedYes) {
                // No change to the underlying flag, just clear the prompt.
                clearWaslPending(leftUid);
                return;
            }
            setIsWaslOnSegment(leftSeg, value);
        } catch (err) {
            console.warn('WaslBoundary: commit failed:', err);
        } finally {
            clearWaslPending(leftUid);
        }
    }

    function revealEdit(): void {
        hovering = true;
    }
    function hideEdit(): void {
        hovering = false;
    }
</script>

{#if sameChapter && leftUid}
    <div
        class="wasl-boundary"
        class:is-prompting={isPending}
        class:is-yes={isCommittedYes}
        on:mouseenter={revealEdit}
        on:mouseleave={hideEdit}
        on:focusin={revealEdit}
        on:focusout={hideEdit}
        role="group"
        aria-label="Wasl boundary between segments"
    >
        <span class="rule" aria-hidden="true"></span>

        {#if isPending}
            <span class="ask">
                <span class="label">waṣl?</span>
                <button
                    type="button"
                    class="choice"
                    use:editGate
                    on:click={() => commit(false)}
                >no</button>
                <span class="dot" aria-hidden="true">·</span>
                <button
                    type="button"
                    class="choice choice-affirm"
                    use:editGate
                    on:click={() => commit(true)}
                >yes</button>
            </span>
        {:else if isCommittedYes}
            <button
                type="button"
                class="committed"
                title="Wasl connection. Click to remove."
                use:editGate
                on:click={() => commit(false)}
            >waṣl</button>
        {:else if hovering}
            <button
                type="button"
                class="reopen"
                title="Mark this boundary as wasl"
                use:editGate
                on:click={() => commit(true)}
            >mark wasl</button>
        {/if}

        <span class="rule" aria-hidden="true"></span>
    </div>
{/if}

<style>
    .wasl-boundary {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        padding: var(--s-1) var(--s-3);
        font-family: var(--font-sans);
        font-size: var(--fs-meta);
        line-height: var(--lh-tight);
        letter-spacing: 0.06em;
        font-variant: small-caps;
        color: var(--text-faint);
        transition: color var(--t-fast) var(--ease-out-quart);
    }
    .wasl-boundary:hover,
    .wasl-boundary.is-prompting,
    .wasl-boundary.is-yes {
        color: var(--text-secondary);
    }

    .rule {
        flex: 1 1 auto;
        height: 0;
        border-top: 1px solid var(--border-quiet);
        transition: border-color var(--t-fast) var(--ease-out-quart);
    }
    .is-prompting .rule,
    .is-yes .rule {
        border-top-color: var(--border-default);
    }

    /* Prompting cluster: small caps label + two text affordances + dot */
    .ask {
        display: inline-flex;
        align-items: baseline;
        gap: var(--s-2);
    }
    .label {
        color: var(--text-secondary);
        font-weight: 500;
    }
    .choice {
        color: var(--text-muted);
        font-variant: small-caps;
        letter-spacing: 0.06em;
        padding: 0;
        background: transparent;
        border: 0;
        cursor: pointer;
        transition: color var(--t-fast) var(--ease-out-quart);
    }
    .choice:hover {
        color: var(--text-primary);
        text-decoration: underline;
        text-underline-offset: 3px;
    }
    .choice-affirm:hover {
        color: var(--accent);
    }
    .dot {
        color: var(--text-faint);
    }

    /* Committed wasl: quiet small-caps reading, accent-tinted, hover reveals
       click-to-clear without changing layout */
    .committed {
        color: var(--accent);
        font-weight: 500;
        font-variant: small-caps;
        letter-spacing: 0.08em;
        padding: 0;
        background: transparent;
        border: 0;
        cursor: pointer;
        transition: color var(--t-fast) var(--ease-out-quart);
    }
    .committed:hover {
        color: var(--accent-strong);
    }

    /* Hover-reveal "mark wasl" affordance for default (untouched) boundaries.
       Lets the user edit historic boundaries without persistent chrome. */
    .reopen {
        color: var(--text-muted);
        font-variant: small-caps;
        letter-spacing: 0.06em;
        padding: 0;
        background: transparent;
        border: 0;
        cursor: pointer;
        transition: color var(--t-fast) var(--ease-out-quart);
    }
    .reopen:hover {
        color: var(--accent);
    }
</style>
