<!--
    Inline claim affordance. Renders only when `task.predicates.can_claim`
    is true, the user is signed in, and the user doesn't already hold a
    different active claim. Clicking opens the global claim-confirm modal
    (one claim path for every entry point); the modal owns the actual
    `claim()` call, the existing-claim warning, and the 409 backstop.
-->
<script lang="ts">
    import { localeStore, tr } from '$lib/i18n/locale-store';
    import * as m from '$lib/paraglide/messages';

    import type { ReciterTask } from '../api/reciter-task';
    import { SIGN_IN_MESSAGES } from '../sign-in-messages';
    import { openClaimConfirm } from '../stores/claim-confirm-modal';
    import { currentUser, isSignedIn } from '../stores/current-user';
    import { openSignInModal } from '../stores/sign-in-modal';

    export let slug: string;
    export let task: ReciterTask | null;
    /** Optional callback invoked after a successful claim — typically the
     *  parent's "refresh reciter-task immediately" hook. */
    export let onClaimed: (() => void) | null = null;

    $: visible =
        $currentUser !== null &&
        isSignedIn($currentUser) &&
        task !== null &&
        task.predicates.can_claim &&
        ($currentUser.active_claim === null ||
            $currentUser.active_claim === slug ||
            $currentUser.role === 'owner');

    function _onClick() {
        if (!isSignedIn($currentUser)) {
            openSignInModal(null, SIGN_IN_MESSAGES.claim);
            return;
        }
        openClaimConfirm(slug, { onClaimed });
    }

    $: claimLabel = tr($localeStore, m.common_claim_button_label());
</script>

{#if visible}
    <button type="button" class="seg-btn primary" on:click={_onClick}>
        {claimLabel}
    </button>
{/if}
