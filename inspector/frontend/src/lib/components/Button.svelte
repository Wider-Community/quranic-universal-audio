<script lang="ts">
    /** Variant controls visual style. */
    export let variant: 'primary' | 'secondary' | 'danger' | 'cancel' | 'confirm' = 'primary';
    /** Size controls padding / font-size. */
    export let size: 'sm' | 'md' = 'md';
    /** Forwarded to the native button element. */
    export let disabled = false;
    /** Optional extra class names to apply (for legacy compatibility). */
    export let extraClass = '';

    $: classes = [
        'btn',
        size === 'sm' ? 'btn-sm' : '',
        variant === 'danger'  ? 'btn-delete'  : '',
        variant === 'cancel'  ? 'btn-cancel'  : '',
        variant === 'confirm' ? 'btn-confirm' : '',
        extraClass,
    ].filter(Boolean).join(' ');
</script>

<button class={classes} {disabled} on:click>
    <slot />
</button>

<style>
    /* Core .btn styles — scoped to this component. Other Svelte components that
     * render buttons directly (without using Button.svelte) still rely on the
     * global .btn rules in styles/components.css. */
    .btn {
        padding: 10px 20px;
        background: #4361ee;
        color: white;
        border: none;
        border-radius: 6px;
        cursor: pointer;
        font-size: 1rem;
        margin-left: auto;
        transition: background 0.2s;
    }
    .btn:hover {
        background: #3a56d4;
    }
    .btn:disabled {
        background: #555;
        cursor: not-allowed;
    }
    .btn-sm {
        padding: 3px 10px;
        font-size: 0.75rem;
    }
    .btn-delete {
        background: #c62828;
    }
    .btn-delete:hover {
        background: #b71c1c;
    }
    .btn-cancel {
        background: #555;
    }
    .btn-cancel:hover {
        background: #666;
    }
    .btn-confirm {
        background: #2e7d32;
    }
    .btn-confirm:hover {
        background: #1b5e20;
    }
</style>
