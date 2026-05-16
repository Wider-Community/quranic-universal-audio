<script lang="ts">
    /** Keyboard-hints footer. */
    import { createEventDispatcher } from 'svelte';

    const dispatch = createEventDispatcher<{ cancel: void }>();
</script>

<div class="row">
    <div class="hints">
        <span class="hint"><span class="key">↑↓</span> navigate</span>
        <span class="hint"><span class="key">↵</span> select</span>
        <span class="hint"><span class="key">Esc</span> close</span>
        <span class="hint"><span class="key">/</span> search</span>
    </div>
    <button type="button" class="cancel" on:click={() => dispatch('cancel')}>Cancel</button>
</div>

<style>
    .row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-4);
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }
    .hints { display: flex; gap: var(--s-4); flex-wrap: wrap; }
    .hint { display: inline-flex; align-items: center; gap: 2px; }
    .key {
        display: inline-block;
        padding: 1px 5px;
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-1);
        font-family: var(--font-mono);
        font-size: 10.5px;
        color: var(--text-secondary);
        margin-right: 4px;
    }
    .cancel {
        background: transparent;
        color: var(--text-muted);
        border: none;
        cursor: pointer;
        font-size: var(--fs-meta);
        text-decoration: underline;
        text-decoration-color: var(--border-default);
        text-underline-offset: 3px;
        padding: 0;
    }
    .cancel:hover { color: var(--text-primary); }
</style>
