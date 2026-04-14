<script lang="ts">
    /**
     * ValidationBadge — stub component for Wave 3 (shell only).
     * Real consumers land in Wave 8 (ValidationPanel.svelte, ErrorCard.svelte).
     *
     * Displays a label + count badge with tonal color coding:
     *   default  — neutral / info
     *   warning  — yellow (e.g. low confidence)
     *   error    — red (e.g. structural issues, failed alignments)
     */

    export let label: string;
    export let count: number;
    export let tone: 'default' | 'warning' | 'error' = 'default';

    $: hasItems = count > 0;
</script>

<span
    class="val-badge"
    class:has-errors={hasItems}
    class:tone-warning={tone === 'warning'}
    class:tone-error={tone === 'error'}
>
    {label}: {count}
</span>

<style>
    .val-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 10px;
        font-size: 0.8rem;
        font-weight: 600;
        background: #2a2a4a;
        color: #aaa;
        border: 1px solid #333;
        white-space: nowrap;
    }
    .val-badge.has-errors {
        background: #1a1a3e;
        color: #ccc;
    }
    .val-badge.has-errors.tone-warning {
        background: #3d2e00;
        color: #f0a500;
        border-color: #5a4400;
    }
    .val-badge.has-errors.tone-error {
        background: #3d0a0a;
        color: #f44336;
        border-color: #5a1010;
    }
</style>
