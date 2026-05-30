<!--
    Single popover surfaced by the `editGate` action when a non-editor
    clicks an edit affordance. Mounted once at app root so multiple
    affordances share one element + one set of dismissal handlers.
-->
<script lang="ts">
    import { onDestroy, onMount, tick } from 'svelte';

    import { get } from 'svelte/store';

    import { refreshReciterTask } from '../api/reciter-task';
    import { openClaimConfirm } from '../stores/claim-confirm-modal';
    import {
        editPopover,
        hideEditPopover,
    } from '../stores/edit-popover';
    import { selectedReciter } from '../../tabs/segments/stores/chapter';

    let popoverEl: HTMLDivElement | null = null;
    let top = 0;
    let left = 0;

    $: state = $editPopover;

    $: title = state ? _titleFor(state.mode.viewReason) : '';
    $: body = state ? _bodyFor(state.mode.viewReason) : '';

    // The popover only fires inside the Segments tab, so the current reciter
    // is the segments `selectedReciter`. The `claimable` reason gets a
    // "Claim review" action that opens the confirm modal for it.
    function _onClaimReview() {
        const slug = get(selectedReciter);
        hideEditPopover();
        if (slug) {
            openClaimConfirm(slug, { onClaimed: () => void refreshReciterTask(slug) });
        }
    }

    function _titleFor(reason: string | undefined): string {
        switch (reason) {
            case 'claimable':
                return 'Claim to edit';
            case 'wrong-assignee':
                return 'Being edited by someone else';
            case 'marked_ready':
                return 'Locked for publish';
            case 'published':
                return 'Already published';
            case 'not-available':
                return 'Not ready to edit yet';
            case 'discarded':
                return 'Reciter unavailable';
            default:
                return 'Not available for editing';
        }
    }

    function _bodyFor(reason: string | undefined): string {
        switch (reason) {
            case 'claimable':
                return 'This reciter is available to work on. Claim it (button below) to start editing its segments.';
            case 'wrong-assignee':
                return 'Another contributor currently holds this reciter. You can browse it read-only, or claim a different one from the dashboard.';
            case 'marked_ready':
                return "You marked this reciter ready for publish, so it's locked. Choose “Continue editing” in the banner to make changes.";
            case 'published':
                return 'This reciter is published and read-only. View its word timestamps on the Timestamps tab.';
            case 'not-available':
                return "This reciter hasn't been prepared for editing yet. It'll open once its recitation has been processed.";
            case 'discarded':
                return 'This reciter has been discarded and is not available for editing.';
            default:
                return 'This reciter is not available for editing.';
        }
    }

    async function _reposition() {
        await tick();
        if (!state || !popoverEl) return;
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
        <div class="edit-popover__actions">
            {#if state.mode.viewReason === 'claimable'}
                <button
                    type="button"
                    class="edit-popover__cta"
                    on:click={_onClaimReview}
                >
                    Claim review
                </button>
            {/if}
            <button
                type="button"
                class="edit-popover__dismiss"
                on:click={hideEditPopover}
            >
                {state.mode.viewReason === 'claimable' ? 'Cancel' : 'OK'}
            </button>
        </div>
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
    .edit-popover__cta {
        background: #f0a500;
        color: #1a1a1a;
        border: 0;
        padding: 6px 12px;
        border-radius: 6px;
        font-weight: 600;
        cursor: pointer;
    }
    .edit-popover__cta:hover {
        background: #ffba2c;
    }
</style>
