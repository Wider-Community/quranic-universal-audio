<script lang="ts">
    /**
     * WaslGap — inter-row affordance for the wasl boundary annotation.
     *
     * Renders in the gap between two adjacent segments (segA on the left,
     * segB on the right). The boundary is owned by segA: ``segA.is_wasl``
     * means "wasl-connected to segB". Click anywhere on the slot toggles
     * the flag through ``setIsWaslOnSegment``, which stages a ``setIsWasl``
     * op in the dirty store (saved on the next Save click).
     *
     * After a cross-verse split, ``_handoffPendingChain`` writes the
     * previous piece's UID to the ``flashWaslGap`` store between ref-edits.
     * This component watches that store: when its own ``segA`` is the
     * targeted left side, it scrolls into view and runs a brief CSS pulse
     * so the reviewer notices the new boundary. No modal — the chip is
     * the only input.
     *
     * Only renders when:
     *   - segB exists (segA is not the last seg)
     *   - segA and segB share a chapter
     *   - segA has a UID (so the dispatcher can fire applyCommand)
     */

    import { onMount } from 'svelte';

    import { editGate } from '../../../../lib/actions/editGate';
    import type { Segment } from '../../../../lib/types/domain';
    import { flashWaslGap } from '../../stores/edit';
    import { setIsWaslOnSegment } from '../../utils/edit/setIsWasl';

    export let segA: Segment;
    export let segB: Segment | null;

    let buttonEl: HTMLButtonElement | undefined;
    let flashing = false;
    let _flashTimer: ReturnType<typeof setTimeout> | null = null;

    $: showSlot =
        segB != null
        && segA.segment_uid != null
        && segA.chapter != null
        && segB.chapter != null
        && segA.chapter === segB.chapter;

    $: isOn = segA.is_wasl === true;

    // Drive the flash + scroll-into-view whenever the store names this
    // segment's UID. Effect runs in onMount-wrapped reactive block so the
    // DOM ref (``buttonEl``) is available; otherwise the first store fire
    // (right after split) would race the mount.
    $: if (
        showSlot
        && segA.segment_uid != null
        && $flashWaslGap === segA.segment_uid
        && buttonEl
    ) {
        flashing = true;
        buttonEl.scrollIntoView({ block: 'center', behavior: 'smooth' });
        if (_flashTimer) clearTimeout(_flashTimer);
        _flashTimer = setTimeout(() => { flashing = false; }, 1600);
    }

    onMount(() => () => {
        if (_flashTimer) clearTimeout(_flashTimer);
    });

    function handleClick(): void {
        try {
            setIsWaslOnSegment(segA, !isOn);
        } catch (err) {
            console.warn('WaslGap: toggle failed:', err);
        }
    }
</script>

{#if showSlot}
    <button
        bind:this={buttonEl}
        type="button"
        class="wasl-gap"
        class:wasl-gap-on={isOn}
        class:wasl-gap-off={!isOn}
        class:wasl-gap-flash={flashing}
        aria-pressed={isOn}
        title={isOn
            ? 'Wasl boundary — click to remove'
            : 'No wasl on this boundary — click to mark as wasl'}
        use:editGate
        on:click={handleClick}
    >
        {#if isOn}
            <span class="wasl-chip">wasl</span>
        {:else}
            <span class="wasl-dotted" aria-hidden="true"></span>
        {/if}
    </button>
{/if}

<style>
    .wasl-gap {
        display: block;
        width: 100%;
        padding: 0;
        margin: 0;
        background: none;
        border: none;
        cursor: pointer;
        text-align: center;
        line-height: 0;
    }
    .wasl-gap-off {
        height: 8px;
    }
    .wasl-gap-on {
        height: 18px;
    }
    .wasl-chip {
        display: inline-block;
        padding: 1px 8px;
        font-size: 0.7rem;
        line-height: 1.2;
        color: #1f3c2e;
        background: #d4f4dd;
        border: 1px dashed #2e7d4a;
        border-radius: 3px;
        font-variant: small-caps;
        letter-spacing: 0.04em;
    }
    .wasl-dotted {
        display: block;
        height: 0;
        border-top: 1px dotted rgba(0, 0, 0, 0.18);
        margin: 3px auto;
        width: 60%;
    }
    .wasl-gap:hover .wasl-dotted {
        border-top-color: rgba(46, 125, 74, 0.6);
    }
    .wasl-gap:hover .wasl-chip {
        background: #e6f7eb;
    }
    .wasl-gap:focus-visible {
        outline: 2px solid #2e7d4a;
        outline-offset: 1px;
    }

    /* Post-split nudge: the chain handoff flashes this chip to draw the
       reviewer's eye toward the new inter-piece boundary. */
    .wasl-gap-flash {
        animation: wasl-gap-pulse 1.6s ease-out 1;
    }
    .wasl-gap-flash .wasl-dotted {
        border-top-color: rgba(46, 125, 74, 0.9);
        border-top-style: dashed;
    }
    @keyframes wasl-gap-pulse {
        0%   { background: rgba(46, 125, 74, 0); }
        18%  { background: rgba(46, 125, 74, 0.28); }
        100% { background: rgba(46, 125, 74, 0); }
    }
</style>
