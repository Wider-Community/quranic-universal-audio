<script lang="ts">
    /**
     * RolePicker — wraps {@link RolePill}. When ``editable`` is false it renders
     * the bare pill (no trigger, no hover affordance, no handlers) so non-owners
     * see exactly the static badge. When ``editable`` is true the pill becomes a
     * trigger that opens a small dropdown of the three assignable roles; picking
     * a different one fires ``onchange``. Click-outside + Escape close it.
     *
     * RolePill stays purely presentational — all interactivity lives here.
     */
    import { onMount } from 'svelte';

    import RolePill from './RolePill.svelte';

    type AssignableRole = 'contributor' | 'maintainer' | 'owner';

    interface Props {
        role: string;
        editable: boolean;
        busy?: boolean;
        onchange: (_role: AssignableRole) => void;
    }
    let { role, editable, busy = false, onchange }: Props = $props();

    const ROLES: AssignableRole[] = ['contributor', 'maintainer', 'owner'];

    let open = $state(false);
    let wrapEl = $state<HTMLSpanElement>();

    function toggle(): void {
        if (busy) return;
        open = !open;
    }

    function pick(next: AssignableRole): void {
        open = false;
        if (next !== role) onchange(next);
    }

    function onDocClick(e: MouseEvent): void {
        if (wrapEl && !wrapEl.contains(e.target as Node)) open = false;
    }
    function onKey(e: KeyboardEvent): void {
        if (e.key === 'Escape') open = false;
    }

    onMount(() => {
        document.addEventListener('click', onDocClick, true);
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('click', onDocClick, true);
            document.removeEventListener('keydown', onKey);
        };
    });
</script>

{#if !editable}
    <RolePill {role} />
{:else}
    <span class="rp-wrap" bind:this={wrapEl}>
        <button
            type="button"
            class="rp-trigger"
            class:open
            aria-haspopup="listbox"
            aria-expanded={open}
            disabled={busy}
            title="Change role"
            onclick={toggle}
        >
            <RolePill {role} />
            <span class="rp-caret" aria-hidden="true">▾</span>
        </button>

        {#if open}
            <div class="rp-menu" role="listbox" aria-label="Set role">
                {#each ROLES as r (r)}
                    <button
                        type="button"
                        class="rp-option"
                        class:current={r === role}
                        role="option"
                        aria-selected={r === role}
                        onclick={() => pick(r)}
                    >
                        <RolePill role={r} />
                        {#if r === role}<span class="rp-check" aria-hidden="true">✓</span>{/if}
                    </button>
                {/each}
            </div>
        {/if}
    </span>
{/if}

<style>
    .rp-wrap {
        position: relative;
        display: inline-flex;
    }
    .rp-trigger {
        display: inline-flex;
        align-items: center;
        gap: 3px;
        background: transparent;
        border: 1px solid transparent;
        border-radius: 999px;
        padding: 1px 4px 1px 1px;
        cursor: pointer;
        transition: border-color var(--t-fast), background var(--t-fast);
    }
    .rp-trigger:hover:not(:disabled),
    .rp-trigger.open {
        border-color: var(--border-strong);
        background: var(--panel);
    }
    .rp-trigger:disabled {
        cursor: progress;
        opacity: 0.6;
    }
    .rp-caret {
        font-size: 9px;
        color: var(--text-faint);
        line-height: 1;
    }
    .rp-trigger:hover:not(:disabled) .rp-caret {
        color: var(--text-muted);
    }

    .rp-menu {
        position: absolute;
        top: calc(100% + 4px);
        left: 0;
        z-index: 50;
        display: flex;
        flex-direction: column;
        gap: 2px;
        padding: 4px;
        min-width: 150px;
        background: var(--canvas-inset, var(--panel));
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        box-shadow: 0 8px 24px oklch(0.06 0.005 268 / 0.5);
    }
    .rp-option {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-3);
        background: transparent;
        border: 0;
        border-radius: var(--r-1);
        padding: var(--s-2) var(--s-2);
        cursor: pointer;
        transition: background var(--t-fast);
    }
    .rp-option:hover {
        background: var(--panel);
    }
    .rp-option.current {
        background: var(--accent-tint-soft, var(--panel));
    }
    .rp-check {
        font-size: 11px;
        color: var(--accent);
    }
</style>
