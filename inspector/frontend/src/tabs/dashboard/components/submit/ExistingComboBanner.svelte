<script lang="ts">
    /**
     * Banner shown above the wizard body. Points contributors with an
     * already-covered combination back to the per-delivery RequestForm
     * (still the canonical edit path). Dismissible per-session; not
     * persisted because PRODUCT.md warns against modal-fatigue patterns.
     */
    export let dismissed = false;
    export let highlighted = false; // pulsed when the user picks an existing reciter + a combination they already cover

    function dismiss(): void {
        dismissed = true;
    }
</script>

{#if !dismissed}
    <aside class="banner" class:highlighted aria-label="Existing combination hint">
        <div class="copy">
            <span class="lede">Editing an existing combination?</span>
            <span class="body">
                Open the reciter, click the combination row, then
                <em>Request alignment</em>.
            </span>
        </div>
        <button type="button" class="dismiss" aria-label="Dismiss hint" on:click={dismiss}>×</button>
    </aside>
{/if}

<style>
    .banner {
        display: flex;
        align-items: flex-start;
        gap: var(--s-3);
        padding: var(--s-3) var(--s-4);
        background: var(--accent-tint-soft);
        border: 1px solid var(--accent-tint);
        border-radius: var(--r-2);
        font-size: var(--fs-meta);
        line-height: 1.45;
        transition: background var(--t-base) var(--ease-out-quart),
                    border-color var(--t-base) var(--ease-out-quart);
    }
    .banner.highlighted {
        background: var(--accent-tint);
        border-color: var(--accent);
        animation: pulse var(--t-slow) var(--ease-out-quart);
    }
    @keyframes pulse {
        0%   { transform: none; }
        45%  { transform: translateY(-1px); }
        100% { transform: none; }
    }
    .copy {
        display: flex;
        flex-direction: column;
        gap: 2px;
        flex: 1;
        min-width: 0;
    }
    .lede {
        color: var(--text-primary);
        font-weight: 500;
    }
    .body {
        color: var(--text-secondary);
    }
    .body em {
        color: var(--text-primary);
        font-style: normal;
        font-family: var(--font-mono);
        font-size: 11px;
        padding: 1px 5px;
        border-radius: var(--r-1);
        background: var(--panel);
        border: 1px solid var(--border-quiet);
    }
    .dismiss {
        flex-shrink: 0;
        width: 22px;
        height: 22px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        color: var(--text-faint);
        font-size: 16px;
        line-height: 1;
        border-radius: var(--r-1);
        transition: color var(--t-fast), background var(--t-fast);
    }
    .dismiss:hover {
        color: var(--text-primary);
        background: var(--accent-tint);
    }
</style>
