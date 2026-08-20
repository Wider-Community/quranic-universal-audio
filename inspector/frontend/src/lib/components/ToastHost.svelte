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
        inset-inline-end: 16px;
        bottom: 16px;
        display: flex;
        flex-direction: column;
        gap: 8px;
        z-index: 10001;
        pointer-events: none;
    }
    .toast {
        pointer-events: auto;
        text-align: start;
        min-width: 300px;
        max-width: 420px;
        padding: 13px 16px;
        border-radius: 8px;
        /* OPAQUE surface — never a translucent tint (a low-alpha fill lets the
           page bleed through and the text becomes unreadable). Kind is conveyed
           by an opaque colored left accent bar + border, not a see-through bg. */
        background: var(--elevated);
        border: 1px solid var(--border-default);
        border-inline-start-width: 5px;
        border-inline-start-color: var(--accent);
        font-size: 0.94rem;
        line-height: 1.4;
        color: var(--text-primary);
        box-shadow: var(--shadow-pop);
        cursor: pointer;
    }
    /* Toast kinds recolor only the left accent bar. */
    .toast--info { border-inline-start-color: var(--accent); }
    .toast--success { border-inline-start-color: var(--ok-solid); }
    .toast--warn { border-inline-start-color: var(--cta-bg); }
    .toast--error { border-inline-start-color: var(--bad-solid); }
</style>
