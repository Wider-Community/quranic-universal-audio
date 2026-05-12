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
        border: 0;
        font-size: 0.92rem;
        line-height: 1.35;
        color: #f5f7ff;
        background: #2c3142;
        box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35);
        cursor: pointer;
    }
    .toast--info { background: #2c3142; }
    .toast--success { background: #15663b; }
    .toast--warn { background: #8a5a00; }
    .toast--error { background: #7a1f1f; }
</style>
