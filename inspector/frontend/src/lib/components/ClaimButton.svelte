<!--
    Inline claim affordance. Renders only when `task.predicates.can_claim`
    is true and the user is signed in. The 409 conflict path (another
    active claim) is now the sole responsibility of `claims-client.ts` —
    this button doesn't render any "hint" state.
-->
<script lang="ts">
    import { claim } from '../api/claims-client';
    import type { ReciterTask } from '../api/reciter-task';
    import { currentUser, isSignedIn } from '../stores/current-user';
    import { openSignInModal } from '../stores/sign-in-modal';

    export let slug: string;
    export let task: ReciterTask | null;
    /** Optional callback invoked after a successful claim — typically the
     *  parent's "refresh reciter-task immediately" hook. */
    export let onClaimed: (() => void) | null = null;

    let busy = false;

    $: visible = (
        $currentUser !== null
        && isSignedIn($currentUser)
        && task !== null
        && task.predicates.can_claim
    );

    async function _onClick() {
        if (busy) return;
        if (!isSignedIn($currentUser)) {
            openSignInModal();
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
    <button
        type="button"
        class="claim-btn"
        disabled={busy}
        on:click={_onClick}
    >
        {busy ? 'Claiming…' : 'Claim'}
    </button>
{/if}

<style>
    .claim-btn {
        background: #f0a500;
        color: #1a1a1a;
        border: 0;
        padding: 6px 14px;
        border-radius: 6px;
        font-weight: 600;
        cursor: pointer;
        font-size: 0.95rem;
        box-shadow: 0 2px 8px rgba(240, 165, 0, 0.25);
        transition: background 0.2s, box-shadow 0.2s;
    }
    .claim-btn:hover:not(:disabled) {
        background: #ffba2c;
        box-shadow: 0 4px 12px rgba(240, 165, 0, 0.4);
    }
    .claim-btn:disabled {
        opacity: 0.6;
        cursor: progress;
    }
</style>
