<script lang="ts">
    /**
     * Segmented control (Svelte 5 runes) — a small inline radio group rendered
     * as a single pill track with one active segment. Token-styled to the
     * system: `panel-2` track, `elevated` + accent text on the active segment,
     * accent focus ring. Generic over its options; used for the email-prefs
     * scope selectors (Off · All · Choose / Off · Follow).
     */
    interface Option {
        value: string;
        label: string;
    }

    interface Props {
        options: Option[];
        value: string;
        onchange: (_next: string) => void;
        ariaLabel?: string;
        disabled?: boolean;
    }

    let { options, value, onchange, ariaLabel, disabled = false }: Props = $props();

    function pick(v: string): void {
        if (disabled || v === value) return;
        onchange(v);
    }
</script>

<div class="seg" class:disabled role="radiogroup" aria-label={ariaLabel}>
    {#each options as opt (opt.value)}
        <button
            type="button"
            role="radio"
            aria-checked={value === opt.value}
            class="seg-btn"
            class:on={value === opt.value}
            {disabled}
            onclick={() => pick(opt.value)}>{opt.label}</button>
    {/each}
</div>

<style>
    .seg {
        display: inline-flex;
        padding: 2px;
        gap: 2px;
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
    }
    .seg.disabled {
        opacity: 0.5;
    }
    .seg-btn {
        appearance: none;
        border: 0;
        background: transparent;
        color: var(--text-muted);
        font-size: var(--fs-meta);
        font-weight: 500;
        line-height: 1;
        padding: 5px 11px;
        border-radius: var(--r-1);
        cursor: pointer;
        white-space: nowrap;
        transition:
            color var(--t-fast),
            background var(--t-fast);
    }
    .seg-btn:hover:not(.on):not(:disabled) {
        color: var(--text-secondary);
    }
    .seg-btn.on {
        background: var(--elevated);
        color: var(--accent-strong);
    }
    .seg-btn:disabled {
        cursor: not-allowed;
    }
    .seg-btn:focus-visible {
        outline: none;
        box-shadow: 0 0 0 2px var(--accent);
    }
    @media (prefers-reduced-motion: reduce) {
        .seg-btn {
            transition: none;
        }
    }
</style>
