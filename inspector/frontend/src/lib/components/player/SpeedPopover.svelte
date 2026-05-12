<script lang="ts">
    /** Speed picker — reuses the SPEEDS constant shared with SpeedControl. */
    import { createEventDispatcher } from 'svelte';

    import { SPEEDS } from '../../utils/speed-control';

    export let value = 1;
    export let open = false;

    const dispatch = createEventDispatcher<{
        change: number;
        toggle: void;
    }>();
</script>

<div class="wrap">
    <button type="button" class="trigger" on:click={() => dispatch('toggle')}>
        {value}×
    </button>
    {#if open}
        <ul class="menu" role="menu">
            {#each SPEEDS as s}
                <li>
                    <button
                        type="button"
                        class="opt"
                        class:active={s === value}
                        on:click={() => dispatch('change', s)}
                    >{s}×{#if s === value} <span class="tick">✓</span>{/if}</button>
                </li>
            {/each}
        </ul>
    {/if}
</div>

<style>
    .wrap {
        position: relative;
    }
    .trigger {
        padding: 4px var(--s-2);
        font-family: var(--font-mono);
        font-size: 11px;
        color: var(--text-secondary);
        background: transparent;
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        cursor: pointer;
        transition: border-color var(--t-fast), color var(--t-fast);
    }
    .trigger:hover {
        border-color: var(--border-strong);
        color: var(--text-primary);
    }
    .menu {
        position: absolute;
        bottom: calc(100% + var(--s-2));
        right: 0;
        list-style: none;
        margin: 0;
        padding: var(--s-1) 0;
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        box-shadow: 0 16px 48px oklch(0 0 0 / 0.45);
        min-width: 88px;
        z-index: 30;
    }
    .opt {
        display: flex;
        align-items: center;
        justify-content: space-between;
        width: 100%;
        padding: var(--s-2) var(--s-3);
        font-family: var(--font-mono);
        font-size: 11.5px;
        color: var(--text-secondary);
        background: transparent;
        border: 0;
        cursor: pointer;
        transition: background var(--t-fast), color var(--t-fast);
        text-align: left;
    }
    .opt:hover {
        background: var(--panel-2);
        color: var(--text-primary);
    }
    .opt.active {
        background: var(--accent-tint);
        color: var(--text-primary);
    }
    .tick { color: var(--accent-strong); margin-left: var(--s-2); }
</style>
