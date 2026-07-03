<!--
    Single popover surfaced by the `editGate` action when a non-editor
    clicks an edit affordance. Mounted once at app root so multiple
    affordances share one element + one set of dismissal handlers.
-->
<script lang="ts">
    import { onDestroy, onMount, tick } from 'svelte';
    import { get } from 'svelte/store';

    import { localeStore, tr } from '../i18n/locale-store';
    import * as m from '../paraglide/messages';
    import { selectedReciter } from '../../tabs/segments/stores/chapter';
    import { refreshReciterTask } from '../api/reciter-task';
    import { openClaimConfirm } from '../stores/claim-confirm-modal';
    import {
        editPopover,
        hideEditPopover,
    } from '../stores/edit-popover';

    let popoverEl: HTMLDivElement | null = null;
    let top = 0;
    let left = 0;

    $: state = $editPopover;

    $: title = state ? tr($localeStore, _titleFor(state.mode.viewReason)) : '';
    $: body = state ? tr($localeStore, _bodyFor(state.mode.viewReason)) : '';

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
                return m.common_edit_gate_title_claimable();
            case 'holds-other-claim':
                return m.common_edit_gate_title_holds_other_claim();
            case 'wrong-assignee':
                return m.common_edit_gate_title_wrong_assignee();
            case 'marked_ready':
                return m.common_edit_gate_title_marked_ready();
            case 'published':
                return m.common_edit_gate_title_published();
            case 'not-available':
                return m.common_edit_gate_title_not_available();
            case 'discarded':
                return m.common_edit_gate_title_discarded();
            default:
                return m.common_edit_gate_title_default();
        }
    }

    function _bodyFor(reason: string | undefined): string {
        switch (reason) {
            case 'claimable':
                return m.common_edit_gate_body_claimable();
            case 'holds-other-claim':
                return m.common_edit_gate_body_holds_other_claim();
            case 'wrong-assignee':
                return m.common_edit_gate_body_wrong_assignee();
            case 'marked_ready':
                return m.common_edit_gate_body_marked_ready();
            case 'published':
                return m.common_edit_gate_body_published();
            case 'not-available':
                return m.common_edit_gate_body_not_available();
            case 'discarded':
                return m.common_edit_gate_body_discarded();
            default:
                return m.common_edit_gate_body_default();
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
                    {tr($localeStore, m.common_claim_button_label())}
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
        background: var(--popover-bg);
        color: var(--text-primary);
        border-radius: 8px;
        box-shadow: var(--shadow-pop);
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
        color: var(--text-primary);
        border: 1px solid var(--hairline-on-color);
        padding: 6px 10px;
        border-radius: 6px;
        cursor: pointer;
    }
    .edit-popover__dismiss:hover {
        border-color: var(--border-strong);
    }
    .edit-popover__cta {
        background: var(--cta-bg);
        color: var(--cta-fg);
        border: 0;
        padding: 6px 12px;
        border-radius: 6px;
        font-weight: 600;
        cursor: pointer;
    }
    .edit-popover__cta:hover {
        background: var(--cta-bg-hover);
    }
</style>
