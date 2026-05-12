<!--
    Inline claim affordance. Renders only when the currently-displayed
    reciter is `awaiting_review`, `public`, the user is signed in, and they
    don't hold another active claim. Otherwise nothing is shown — there is
    no "locked" banner for non-claimable rows (Phase 3 design).

    On click:
      - anonymous → open SignInModal (claims-client handles the 401 path).
      - signed-in → POST /api/claim/<slug>; on success, claim-client refreshes
        currentUser.active_claim so the rest of the UI flips into editor mode
        on the next poll tick (or immediately via the parent's refresh).
-->
<script lang="ts">
    import { claim } from '../api/claims-client';
    import type { ReciterTask } from '../api/reciter-task';
    import { currentUser, isSignedIn } from '../stores/current-user';
    import { openSignInModal } from '../stores/sign-in-modal';
    import { pushToast } from '../stores/toast';

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

    /** When the user is signed in but the predicate is false because they
     *  hold another active claim, show a small hint button instead — clicking
     *  surfaces the toast explaining how to free it. Hidden for anonymous
     *  and for non-awaiting_review rows. */
    $: hintMode = (
        $currentUser !== null
        && isSignedIn($currentUser)
        && task !== null
        && task.row.state === 'awaiting_review'
        && task.row.visibility === 'public'
        && $currentUser.active_claim !== null
        && $currentUser.active_claim !== slug
    );

    async function _onClick() {
        if (busy) return;
        if (!isSignedIn($currentUser)) {
            openSignInModal();
            return;
        }
        if (hintMode) {
            pushToast({
                kind: 'warn',
                text: `Release ${$currentUser.active_claim} first to claim ${slug}.`,
                ttl: 5000,
            });
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
{:else if hintMode}
    <button
        type="button"
        class="claim-btn claim-btn--hint"
        on:click={_onClick}
        title="You already hold another active claim. Release it first."
    >
        Already claiming another reciter
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
    .claim-btn--hint {
        background: transparent;
        color: #d99a3a;
        border: 1px dashed #8a5a00;
        font-weight: 500;
        box-shadow: none;
    }
    .claim-btn--hint:hover {
        background: rgba(240, 165, 0, 0.1);
        color: #f0a500;
        box-shadow: none;
    }
</style>
