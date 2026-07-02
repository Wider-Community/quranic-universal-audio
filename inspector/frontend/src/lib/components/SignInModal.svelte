<!--
    Sign-in modal. Mounted once at the app root and surfaced via
    `openSignInModal()` whenever an anonymous user attempts a
    contribution action (claim, save, etc.).

    Standalone tab: the CTA kicks off the plain redirect sign-in.
    Embedded HF iframe: the CTA runs the silent in-iframe flow
    (`embedded-auth.ts`); if the browser won't complete it in-frame, the modal
    offers a single "continue in a new tab" link (a click is required — browsers
    block auto-opening tabs). See `embedded-auth.ts` for the constraints.
-->
<script lang="ts">
    import { signIn } from '../api/auth-client';
    import {
        beginEmbeddedSignIn,
        continueInTab,
        embeddedAuth,
        isEmbedded,
        recheckSession,
        resetEmbeddedAuth,
    } from '../api/embedded-auth';
    import { closeSignInModal, signInModal } from '../stores/sign-in-modal';

    $: title = $signInModal.context?.title ?? 'Sign in to contribute';
    $: body = $signInModal.context?.body ?? 'Sign in with your Hugging Face account to claim a reciter and edit segments. We only read your username and avatar — nothing else.';
    $: returnPath = $signInModal.returnPath ?? '/';
    $: phase = $embeddedAuth.phase;
    $: embedded = isEmbedded();

    // Success: identity is already loaded by the flow — just close.
    $: if ($signInModal.open && phase === 'done') _close();

    function _onContinue() {
        if (embedded) {
            void beginEmbeddedSignIn(returnPath);
        } else {
            closeSignInModal();
            signIn(returnPath);
        }
    }

    function _close() {
        closeSignInModal();
        resetEmbeddedAuth();
    }

    function _onBackdropClick(e: MouseEvent) {
        if (e.target === e.currentTarget) _close();
    }

    function _onKeydown(e: KeyboardEvent) {
        if (e.key === 'Escape') _close();
    }
</script>

<svelte:window on:keydown={_onKeydown} />

{#if $signInModal.open}
    <div class="sign-in-backdrop" on:click={_onBackdropClick} role="presentation">
        <div
            class="sign-in-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="sign-in-title"
        >
            {#if embedded && phase === 'trying'}
                <h2 id="sign-in-title" class="sign-in-title">Signing you in…</h2>
                <p class="sign-in-body">Connecting to your Hugging Face account.</p>
            {:else if embedded && phase === 'need-tab'}
                <h2 id="sign-in-title" class="sign-in-title">One more step</h2>
                <p class="sign-in-body">
                    Your browser won't let sign-in finish inside this embedded
                    view. Continue in a new tab — you'll come right back here,
                    signed in.
                </p>
                <div class="sign-in-actions">
                    <button type="button" class="sign-in-cta" on:click={continueInTab}>
                        Continue in a new tab
                    </button>
                    <button type="button" class="sign-in-dismiss" on:click={_close}>Cancel</button>
                </div>
            {:else if embedded && phase === 'awaiting-tab'}
                <h2 id="sign-in-title" class="sign-in-title">Finish in the new tab</h2>
                <p class="sign-in-body">
                    Complete sign-in in the tab that just opened, then return
                    here. This updates automatically.
                </p>
                <div class="sign-in-actions">
                    <button type="button" class="sign-in-cta" on:click={() => void recheckSession()}>
                        I've signed in
                    </button>
                    <button type="button" class="sign-in-dismiss" on:click={_close}>Cancel</button>
                </div>
            {:else}
                <h2 id="sign-in-title" class="sign-in-title">{title}</h2>
                <p class="sign-in-body">{body}</p>
                <div class="sign-in-actions">
                    <button type="button" class="sign-in-cta" on:click={_onContinue}>
                        Continue with Hugging Face
                    </button>
                    <button type="button" class="sign-in-dismiss" on:click={_close}>Cancel</button>
                </div>
            {/if}
        </div>
    </div>
{/if}

<style>
    .sign-in-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(8, 10, 16, 0.65);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10000;
    }
    .sign-in-modal {
        background: #16213e;
        color: #f5f7ff;
        border: 1px solid #2a2a4a;
        padding: 20px 22px;
        border-radius: 10px;
        max-width: 420px;
        width: calc(100% - 32px);
        box-shadow:
            0 12px 36px rgba(0, 0, 0, 0.55),
            0 1px 2px rgba(0, 0, 0, 0.3);
    }
    .sign-in-title {
        margin: 0 0 8px;
        font-size: 1.15rem;
        color: #fff;
    }
    .sign-in-body {
        color: #ccc;
        margin: 0 0 16px;
        font-size: 0.95rem;
        line-height: 1.45;
    }
    .sign-in-actions {
        display: flex;
        gap: 8px;
        justify-content: flex-end;
    }
    .sign-in-cta {
        background: #f0a500;
        color: #1a1a1a;
        border: 0;
        padding: 8px 14px;
        border-radius: 6px;
        font-weight: 600;
        cursor: pointer;
    }
    .sign-in-cta:hover {
        background: #ffba2c;
    }
    .sign-in-dismiss {
        background: transparent;
        color: #ccc;
        border: 1px solid #333;
        padding: 8px 14px;
        border-radius: 6px;
        cursor: pointer;
    }
    .sign-in-dismiss:hover {
        border-color: #4cc9f0;
        color: #4cc9f0;
    }
</style>
