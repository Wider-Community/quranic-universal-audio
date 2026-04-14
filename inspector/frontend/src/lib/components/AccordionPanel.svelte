<script lang="ts">
    /**
     * AccordionPanel — a <details> wrapper with data-category support and
     * two-way open binding.
     *
     * The existing shared/accordion.ts helpers (collapseSiblingDetails,
     * capturePanelOpenState, restorePanelOpenState) stay in shared/ for now
     * and continue to be used by the imperative validation panel code.
     * Wave 8 decides whether to absorb them here or keep them as pure utilities.
     */

    /** Human-readable label for the accordion header. */
    export let label: string;
    /** Category identifier for data-category attribute + open-state keying. */
    export let category: string;
    /** Two-way open state. Parent can bind:open={myVar} to capture/restore. */
    export let open = false;

    function onToggle(e: Event): void {
        open = (e.target as HTMLDetailsElement).open;
    }
</script>

<details data-category={category} {open} on:toggle={onToggle}>
    <summary>{label}</summary>
    <slot />
</details>

<style>
    details {
        border: 1px solid #2a2a4a;
        border-radius: 6px;
        margin-bottom: 8px;
        overflow: hidden;
    }
    summary {
        padding: 8px 12px;
        cursor: pointer;
        background: #16213e;
        user-select: none;
        font-size: 0.9rem;
        color: #ccc;
        list-style: none;
    }
    summary:hover {
        background: #1a2a4e;
    }
    summary::marker,
    summary::-webkit-details-marker {
        display: none;
    }
    summary::before {
        content: '▶ ';
        font-size: 0.7em;
        transition: transform 0.15s;
        display: inline-block;
    }
    details[open] summary::before {
        transform: rotate(90deg);
    }
</style>
