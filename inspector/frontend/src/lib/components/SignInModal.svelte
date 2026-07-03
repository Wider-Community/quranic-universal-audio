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
                <h2 id="sign-in-title" class="sign-in-title">Signing in…</h2>
            {:else if embedded && phase === 'need-tab'}
                <h2 id="sign-in-title" class="sign-in-title">Continue in a new tab</h2>
                <p class="sign-in-body">
                    This browser blocks sign-in inside embedded pages.
                </p>
                <div class="sign-in-actions">
                    <button type="button" class="sign-in-cta" on:click={continueInTab}>
                        Open new tab
                    </button>
                    <button type="button" class="sign-in-dismiss" on:click={_close}>Cancel</button>
                </div>
            {:else if embedded && phase === 'awaiting-tab'}
                <h2 id="sign-in-title" class="sign-in-title">Waiting for sign-in</h2>
                <p class="sign-in-body">Finish in the other tab.</p>
                <div class="sign-in-actions">
                    <button type="button" class="sign-in-cta" on:click={() => void recheckSession()}>
                        Recheck
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
        background: var(--scrim-strong);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10000;
    }
    .sign-in-modal {
        background: var(--panel);
        color: var(--text-primary);
        border: 1px solid var(--border-default);
        padding: 20px 22px;
        border-radius: 10px;
        max-width: 420px;
        width: calc(100% - 32px);
        box-shadow: var(--shadow-modal);
    }
    .sign-in-title {
        margin: 0 0 8px;
        font-size: 1.15rem;
        color: var(--text-primary);
    }
    .sign-in-body {
        color: var(--text-secondary);
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
        background: var(--cta-bg);
        color: var(--cta-fg);
        border: 0;
        padding: 8px 14px;
        border-radius: 6px;
        font-weight: 600;
        cursor: pointer;
    }
    .sign-in-cta:hover {
        background: var(--cta-bg-hover);
    }
    .sign-in-dismiss {
        background: transparent;
        color: var(--text-secondary);
        border: 1px solid var(--border-default);
        padding: 8px 14px;
        border-radius: 6px;
        cursor: pointer;
    }
    .sign-in-dismiss:hover {
        border-color: var(--accent);
        color: var(--accent);
    }
</style>
