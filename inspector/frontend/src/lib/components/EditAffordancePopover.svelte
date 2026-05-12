<!--
    Single popover surfaced by the `editGate` action when a non-editor
    clicks an edit affordance. Mounted once at app root so multiple
    affordances share one element + one set of dismissal handlers.
-->
<script lang="ts">
    import { onDestroy, onMount, tick } from 'svelte';

    import {
        editPopover,
        hideEditPopover,
    } from '../stores/edit-popover';

    let popoverEl: HTMLDivElement | null = null;
    let top = 0;
    let left = 0;

    $: state = $editPopover;

    $: title = state ? _titleFor(state.mode.viewReason) : '';
    $: body = state ? _bodyFor(state.mode.viewReason) : '';
    $: showSignIn = state?.mode.viewReason === 'unauthenticated';

    function _titleFor(reason: string | undefined): string {
        switch (reason) {
            case 'wrong-assignee':
                return 'Reciter under review';
            case 'marked_ready':
                return 'Awaiting publish';
            case 'released':
                return 'Awaiting timestamps';
            case 'completed':
                return 'Reciter completed';
            case 'not-claimable':
                return 'Not available for editing';
            case 'discarded':
                return 'Reciter unavailable';
            case 'unauthenticated':
            default:
                return 'Sign in to edit';
        }
    }

    function _bodyFor(reason: string | undefined): string {
        switch (reason) {
            case 'wrong-assignee':
                return 'This reciter is currently being reviewed by another contributor.';
            case 'marked_ready':
                return "You marked this reciter ready for publish. Click 'Continue editing' in the banner to make changes.";
            case 'released':
                return 'This reciter is awaiting timestamp generation; edits are locked.';
            case 'completed':
                return 'This reciter is completed and view-only.';
            case 'not-claimable':
                return 'This reciter is in a pipeline state and cannot be claimed yet.';
            case 'discarded':
                return 'This reciter is not available for editing.';
            case 'unauthenticated':
            default:
                return 'Editing requires a Hugging Face account. Sign in to claim this reciter and start contributing.';
        }
    }

    async function _reposition() {
        if (!state || !popoverEl) return;
        await tick();
        const rect = state.anchor.getBoundingClientRect();
        const popRect = popoverEl.getBoundingClientRect();
        const margin = 8;
        // Default: below the trigger, left-aligned.
        let t = rect.bottom + margin;
        let l = rect.left;
        // Flip up if it would overflow the viewport.
        if (t + popRect.height > window.innerHeight - margin) {
            t = Math.max(margin, rect.top - popRect.height - margin);
        }
        // Clamp horizontally inside the viewport.
        if (l + popRect.width > window.innerWidth - margin) {
            l = Math.max(margin, window.innerWidth - popRect.width - margin);
        }
        top = t + window.scrollY;
        left = l + window.scrollX;
    }

    function _onDocumentClick(e: MouseEvent) {
        if (!state || !popoverEl) return;
        const target = e.target as Node | null;
        if (!target) return;
        if (popoverEl.contains(target)) return;
        if (state.anchor.contains(target)) return;
        hideEditPopover();
    }

    function _onKeydown(e: KeyboardEvent) {
        if (e.key === 'Escape') hideEditPopover();
    }

    function _onSignIn() {
        const next = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.href = `/api/auth/login?return=${next}`;
    }

    $: if (state) void _reposition();

    onMount(() => {
        // Use capture so the dismiss runs before any in-page handler.
        document.addEventListener('click', _onDocumentClick, { capture: true });
        document.addEventListener('keydown', _onKeydown);
        window.addEventListener('resize', _reposition);
        window.addEventListener('scroll', _reposition, { passive: true });
    });

    onDestroy(() => {
        document.removeEventListener('click', _onDocumentClick, { capture: true });
        document.removeEventListener('keydown', _onKeydown);
        window.removeEventListener('resize', _reposition);
        window.removeEventListener('scroll', _reposition);
    });
</script>

{#if state}
    <div
        bind:this={popoverEl}
        class="edit-popover"
        role="dialog"
        aria-label={title}
        style="top: {top}px; left: {left}px;"
    >
        <div class="edit-popover__title">{title}</div>
        <div class="edit-popover__body">{body}</div>
        {#if showSignIn}
            <div class="edit-popover__actions">
                <button
                    type="button"
                    class="edit-popover__cta"
                    on:click={_onSignIn}
                >
                    Sign in with Hugging Face
                </button>
                <button
                    type="button"
                    class="edit-popover__dismiss"
                    on:click={hideEditPopover}
                >
                    Dismiss
                </button>
            </div>
        {:else}
            <div class="edit-popover__actions">
                <button
                    type="button"
                    class="edit-popover__dismiss"
                    on:click={hideEditPopover}
                >
                    OK
                </button>
            </div>
        {/if}
    </div>
{/if}

<style>
    .edit-popover {
        position: absolute;
        z-index: 9999;
        max-width: 320px;
        padding: 12px 14px;
        background: #1f2230;
        color: #f5f7ff;
        border-radius: 8px;
        box-shadow:
            0 8px 24px rgba(0, 0, 0, 0.35),
            0 1px 2px rgba(0, 0, 0, 0.2);
        font-size: 0.9rem;
        line-height: 1.4;
    }
    .edit-popover__title {
        font-weight: 600;
        margin-bottom: 4px;
    }
    .edit-popover__body {
        opacity: 0.85;
        margin-bottom: 10px;
    }
    .edit-popover__actions {
        display: flex;
        gap: 8px;
        justify-content: flex-end;
    }
    .edit-popover__cta {
        background: #f0a500;
        color: #1a1a1a;
        border: 0;
        padding: 6px 10px;
        border-radius: 6px;
        font-weight: 600;
        cursor: pointer;
    }
    .edit-popover__cta:hover {
        background: #ffba2c;
    }
    .edit-popover__dismiss {
        background: transparent;
        color: #f5f7ff;
        border: 1px solid rgba(255, 255, 255, 0.2);
        padding: 6px 10px;
        border-radius: 6px;
        cursor: pointer;
    }
    .edit-popover__dismiss:hover {
        border-color: rgba(255, 255, 255, 0.5);
    }
</style>
