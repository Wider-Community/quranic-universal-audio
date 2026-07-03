<!--
    Claim-confirm modal. Mounted once at the app root and surfaced via
    `openClaimConfirm(slug)` from every claim entry point (inline ClaimButton,
    edit-affordance popover, dashboard reciter modal). Confirms the deliberate
    "claim this reciter for review" action before it fires.

    If the user already holds another claim (one-at-a-time policy), it shows a
    warning variant instead of the confirm — so they release first rather than
    hit a 409. Owners may hold multiple claims, so the warning is skipped for them.
-->
<script lang="ts">
    import { localeStore, tr } from '$lib/i18n/locale-store';
    import * as m from '$lib/paraglide/messages';

    import { loadCatalog } from '../../tabs/dashboard/stores/catalog-data';
    import { claim } from '../api/claims-client';
    import { refreshReciterTask } from '../api/reciter-task';
    import { claimConfirmModal, closeClaimConfirm } from '../stores/claim-confirm-modal';
    import { currentUser, loadCurrentUser } from '../stores/current-user';
    import { titleCaseSlug } from '../utils/delivery-label';

    let busy = false;

    $: lang = $localeStore;
    $: state = $claimConfirmModal;
    $: slug = state.slug;

    // One-claim-at-a-time pre-check: a non-owner who already holds a DIFFERENT
    // active claim must release it first. Owners are exempt.
    $: otherClaim =
        $currentUser.role !== 'owner' &&
        $currentUser.active_claim !== null &&
        $currentUser.active_claim !== slug
            ? $currentUser.active_claim
            : null;
    $: otherClaimName = otherClaim ? titleCaseSlug(otherClaim) : '';

    $: releaseFirstTitle = tr(lang, m.common_claim_confirm_release_first_title());
    $: releaseFirstBody = tr(lang, m.common_claim_confirm_release_first_body({ name: otherClaimName }));
    $: okLabel = tr(lang, m.common_action_ok());
    $: confirmTitle = tr(lang, m.common_claim_confirm_title());
    $: confirmBody = tr(lang, m.common_claim_confirm_body());
    $: confirmCtaLabel = tr(lang, busy ? m.common_claim_confirm_busy() : m.common_claim_confirm_cta());
    $: cancelLabel = tr(lang, m.common_action_cancel());

    async function _onConfirm() {
        if (busy || !slug) return;
        busy = true;
        try {
            await claim(slug);
            // Re-sync everything the claim flips: /api/me (active_claim), the
            // reciter-task (predicates/assignee → edit gate), and the catalog
            // (footer chip + picker bucket). Mirrors SegmentsTab._refreshTask.
            const onClaimed = state.onClaimed;
            await loadCurrentUser();
            await refreshReciterTask(slug);
            void loadCatalog(true);
            closeClaimConfirm();
            onClaimed?.();
        } catch {
            // claims-client already surfaced a friendly toast (incl. the 409
            // backstop if the pre-check was bypassed). Keep the modal open so
            // the user can read it, but drop the busy state.
        } finally {
            busy = false;
        }
    }

    function _onBackdropClick(e: MouseEvent) {
        if (e.target === e.currentTarget) closeClaimConfirm();
    }

    function _onKeydown(e: KeyboardEvent) {
        if (e.key === 'Escape') closeClaimConfirm();
    }
</script>

<svelte:window on:keydown={_onKeydown} />

{#if state.open}
    <div class="claim-backdrop" on:click={_onBackdropClick} role="presentation">
        <div
            class="claim-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="claim-confirm-title"
        >
            {#if otherClaim}
                <h2 id="claim-confirm-title" class="claim-title">{releaseFirstTitle}</h2>
                <p class="claim-body">{releaseFirstBody}</p>
                <div class="claim-actions">
                    <button type="button" class="claim-dismiss" on:click={closeClaimConfirm}>
                        {okLabel}
                    </button>
                </div>
            {:else}
                <h2 id="claim-confirm-title" class="claim-title">{confirmTitle}</h2>
                <p class="claim-body">{confirmBody}</p>
                <div class="claim-actions">
                    <button
                        type="button"
                        class="claim-cta"
                        disabled={busy}
                        on:click={_onConfirm}
                    >
                        {confirmCtaLabel}
                    </button>
                    <button type="button" class="claim-dismiss" on:click={closeClaimConfirm}>
                        {cancelLabel}
                    </button>
                </div>
            {/if}
        </div>
    </div>
{/if}

<style>
    .claim-backdrop {
        position: fixed;
        inset: 0;
        background: var(--scrim-strong);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10000;
    }
    .claim-modal {
        background: var(--panel);
        color: var(--text-primary);
        border: 1px solid var(--border-default);
        padding: 20px 22px;
        border-radius: 10px;
        max-width: 440px;
        width: calc(100% - 32px);
        box-shadow: var(--shadow-modal);
    }
    .claim-title {
        margin: 0 0 8px;
        font-size: 1.15rem;
        color: var(--text-primary);
    }
    .claim-body {
        color: var(--text-secondary);
        margin: 0 0 16px;
        font-size: 0.95rem;
        line-height: 1.45;
    }
    .claim-actions {
        display: flex;
        gap: 8px;
        justify-content: flex-end;
    }
    .claim-cta {
        background: var(--cta-bg);
        color: var(--cta-fg);
        border: 0;
        padding: 8px 14px;
        border-radius: 6px;
        font-weight: 600;
        cursor: pointer;
    }
    .claim-cta:hover {
        background: var(--cta-bg-hover);
    }
    .claim-cta:disabled {
        opacity: 0.6;
        cursor: default;
    }
    .claim-dismiss {
        background: transparent;
        color: var(--text-secondary);
        border: 1px solid var(--border-default);
        padding: 8px 14px;
        border-radius: 6px;
        cursor: pointer;
    }
    .claim-dismiss:hover {
        border-color: var(--accent);
        color: var(--accent);
    }
</style>
