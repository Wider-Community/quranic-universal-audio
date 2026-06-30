<!--
    Single global toast host. Mounted at app root.
    Reads from `lib/stores/toast.ts` and renders the current queue
    bottom-right. Auto-dismissal is handled in the store; click-to-dismiss
    falls through to the same `dismissToast(id)`.
-->
<script lang="ts">
    import { dismissToast, toasts } from '../stores/toast';
</script>

<div class="toast-host" aria-live="polite">
    {#each $toasts as t (t.id)}
        <button
            type="button"
            class="toast toast--{t.kind}"
            on:click={() => dismissToast(t.id)}
        >
            {t.text}
        </button>
    {/each}
</div>

<style>
    .toast-host {
        position: fixed;
        right: 16px;
        bottom: 16px;
        display: flex;
        flex-direction: column;
        gap: 8px;
        z-index: 10001;
        pointer-events: none;
    }
    .toast {
        pointer-events: auto;
        text-align: left;
        max-width: 360px;
        padding: 10px 14px;
        border-radius: 6px;
        border: 1px solid transparent;
        font-size: 0.92rem;
        line-height: 1.35;
        color: var(--text-primary);
        background: var(--panel);
        box-shadow: var(--shadow-pop);
        cursor: pointer;
    }
    /* Toast kinds: surfaces with a tinted left-edge accent via border. */
    .toast--info {
        background: var(--panel);
        border-color: var(--accent);
    }
    .toast--success {
        background: var(--ok-tint);
        border-color: var(--ok-solid);
    }
    .toast--warn {
        background: var(--warn-tint);
        border-color: var(--cta-bg);
    }
    .toast--error {
        background: var(--bad-tint);
        border-color: var(--bad-solid);
    }
</style>
