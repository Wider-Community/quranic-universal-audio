<script lang="ts">
    /**
     * Modal — accessible modal shell with focus trap, Esc close,
     * backdrop click close, and body scroll lock for the lifetime of
     * the open state.
     *
     * Consumers supply the body via the default slot and optionally a
     * footer via the named slot. The header is rendered iff `title` is
     * set; consumers wanting a custom header should pass an empty title
     * and use the `header` slot.
     */
    import { createEventDispatcher, onDestroy, tick } from 'svelte';

    export let open = false;
    export let title: string | null = null;
    /** Accessible label for the close button. */
    export let closeLabel = 'Close';
    /** ``'wide'`` gives a near-fullscreen shell (admin dashboard);
     * ``'narrow'`` hugs its content (reading-width info / prose modals).
     * Default leaves every existing caller unchanged. */
    export let size: 'default' | 'wide' | 'narrow' = 'default';
    /** Raise the modal above other stacked overlays (e.g. opened on top of the
     * segments guides gate). Default keeps the normal layer. */
    export let elevated = false;

    const dispatch = createEventDispatcher<{ close: void }>();

    let modalEl: HTMLDivElement | null = null;
    let previouslyFocused: HTMLElement | null = null;
    let scrollLocked = false;

    $: void manageOpen(open);

    async function manageOpen(o: boolean): Promise<void> {
        if (o) {
            previouslyFocused = document.activeElement as HTMLElement | null;
            lockScroll();
            await tick();
            focusFirst();
        } else {
            unlockScroll();
            previouslyFocused?.focus?.();
            previouslyFocused = null;
        }
    }

    function lockScroll(): void {
        if (scrollLocked) return;
        scrollLocked = true;
        document.body.style.overflow = 'hidden';
    }

    function unlockScroll(): void {
        if (!scrollLocked) return;
        scrollLocked = false;
        document.body.style.overflow = '';
    }

    function focusFirst(): void {
        if (!modalEl) return;
        const focusable = getFocusable();
        const first = focusable[0];
        if (first) first.focus();
        else modalEl.focus();
    }

    function getFocusable(): HTMLElement[] {
        if (!modalEl) return [];
        return Array.from(
            modalEl.querySelectorAll<HTMLElement>(
                'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
            ),
        );
    }

    function onKey(e: KeyboardEvent): void {
        if (e.key === 'Escape') {
            e.preventDefault();
            dispatch('close');
            return;
        }
        if (e.key !== 'Tab') return;
        const focusable = getFocusable();
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (!first || !last) {
            e.preventDefault();
            return;
        }
        const active = document.activeElement as HTMLElement | null;
        if (e.shiftKey && active === first) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && active === last) {
            e.preventDefault();
            first.focus();
        }
    }

    function onBackdropClick(e: MouseEvent): void {
        if (e.target === e.currentTarget) dispatch('close');
    }

    onDestroy(() => unlockScroll());
</script>

{#if open}
    <div
        class="backdrop"
        class:elevated
        on:click={onBackdropClick}
        on:keydown={onKey}
        role="presentation"
    >
        <div
            class="modal"
            class:wide={size === 'wide'}
            class:narrow={size === 'narrow'}
            bind:this={modalEl}
            role="dialog"
            aria-modal="true"
            aria-label={title ?? closeLabel}
            tabindex="-1"
        >
            {#if title || $$slots.header}
                <header class="modal-header">
                    {#if $$slots.header}
                        <slot name="header" />
                    {:else}
                        <h2 class="modal-title">{title}</h2>
                    {/if}
                    <button
                        type="button"
                        class="modal-close"
                        aria-label={closeLabel}
                        on:click={() => dispatch('close')}
                    >×</button>
                </header>
            {:else}
                <button
                    type="button"
                    class="modal-close floating-close"
                    aria-label={closeLabel}
                    on:click={() => dispatch('close')}
                >×</button>
            {/if}

            <div class="modal-body">
                <slot />
            </div>

            {#if $$slots.footer}
                <footer class="modal-footer">
                    <slot name="footer" />
                </footer>
            {/if}
        </div>
    </div>
{/if}

<style>
    .backdrop {
        position: fixed;
        inset: 0;
        background: oklch(0.06 0.005 268 / 0.72);
        backdrop-filter: blur(3px);
        z-index: 120;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: var(--s-6);
        animation: backdrop-in var(--t-slow) var(--ease-out-quart);
    }
    /* Stack above the segments guides gate (z 950) / accordion guide (z 1000)
     * when an info modal is opened on top of them. */
    .backdrop.elevated { z-index: 1050; }
    @keyframes backdrop-in { from { opacity: 0; } to { opacity: 1; } }

    .modal {
        position: relative;
        width: min(1080px, 92vw);
        height: min(720px, 86vh);
        background: var(--canvas);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        display: flex;
        flex-direction: column;
        overflow: hidden;
        box-shadow: 0 32px 80px oklch(0 0 0 / 0.45),
                    0 2px 8px oklch(0 0 0 / 0.3);
        animation: modal-in var(--t-slow) var(--ease-out-expo);
    }
    .modal.wide {
        width: min(1480px, 95vw);
        height: min(900px, 92vh);
    }
    .modal.narrow {
        width: min(640px, 94vw);
        height: auto;
        max-height: 86vh;
    }
    @keyframes modal-in {
        from { opacity: 0; transform: translateY(12px) scale(0.985); }
        to   { opacity: 1; transform: none; }
    }

    .modal-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: var(--s-4) var(--s-6);
        border-bottom: 1px solid var(--border-quiet);
        flex-shrink: 0;
    }
    .modal-title {
        font-size: var(--fs-h3);
        font-weight: 500;
        color: var(--text-primary);
        letter-spacing: 0.005em;
        margin: 0;
    }
    .modal-close {
        width: 32px;
        height: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--text-muted);
        background: transparent;
        border: none;
        border-radius: var(--r-2);
        font-size: 18px;
        cursor: pointer;
        transition: color var(--t-fast), background var(--t-fast);
    }
    .modal-close:hover {
        color: var(--text-primary);
        background: var(--panel);
    }

    .modal-body {
        flex: 1;
        min-height: 0;
        overflow: auto;
    }

    .modal-footer {
        padding: var(--s-3) var(--s-6);
        border-top: 1px solid var(--border-quiet);
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-shrink: 0;
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }
    .floating-close {
        position: absolute;
        top: var(--s-4);
        right: var(--s-4);
        z-index: 10;
        background: var(--panel);
        border: 1px solid var(--border-quiet);
    }

    @media (max-width: 767px) {
        .backdrop {
            padding: var(--s-2);
        }
        .modal {
            width: 100%;
            height: 100%;
        }
        .modal-header {
            align-items: flex-start;
            padding: var(--s-3) var(--s-4);
        }
        .modal-close {
            margin-top: -2px;
        }
    }
</style>
