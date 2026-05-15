<!--
    Inline claim affordance. Renders only when `task.predicates.can_claim`
    is true, the user is signed in, and the user doesn't already hold a
    different active claim. The 409 conflict path is the sole responsibility
    of `claims-client.ts` — this button doesn't render any "hint" state.
-->
<script lang="ts">
    import { claim } from '../api/claims-client';
    import type { ReciterTask } from '../api/reciter-task';
    import { SIGN_IN_MESSAGES } from '../sign-in-messages';
    import { currentUser, isSignedIn } from '../stores/current-user';
    import { openSignInModal } from '../stores/sign-in-modal';

    export let slug: string;
    export let task: ReciterTask | null;
    /** Optional callback invoked after a successful claim — typically the
     *  parent's "refresh reciter-task immediately" hook. */
    export let onClaimed: (() => void) | null = null;

    let busy = false;

    $: visible =
        $currentUser !== null &&
        isSignedIn($currentUser) &&
        task !== null &&
        task.predicates.can_claim &&
        ($currentUser.active_claim === null ||
            $currentUser.active_claim === slug ||
            $currentUser.role === 'owner');

    async function _onClick() {
        if (busy) return;
        if (!isSignedIn($currentUser)) {
            openSignInModal(null, SIGN_IN_MESSAGES.claim);
            return;
        }
        busy = true;
        try {
            await claim(slug);
            onClaimed?.();
        } catch {
            /* claims-client already surfaced the toast */
        } finally {
            busy = false;
        }
    }
</script>

{#if visible}
    <button type="button" class="seg-btn primary" disabled={busy} on:click={_onClick}>
        {busy ? 'Claiming…' : 'Claim'}
    </button>
{/if}
