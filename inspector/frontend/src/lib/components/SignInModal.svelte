<!--
    Sign-in modal. Mounted once at the app root and surfaced via
    `openSignInModal()` whenever an anonymous user attempts a
    contribution action (claim, save, etc.).

    Standalone tab: the CTA kicks off the plain redirect sign-in.
    Embedded HF iframe: the CTA runs the popup + Storage Access flow
    (`embedded-auth.ts`) and this modal renders its phases (waiting for the
    popup, a one-click "finish", and an own-tab fallback if storage access is
    denied). See `embedded-auth.ts` for why the redirect can't work in-frame.
-->
<script lang="ts">
    import { signIn } from '../api/auth-client';
    import {
        beginEmbeddedSignIn,
        continueWithStorageAccess,
        embeddedAuth,
        isEmbedded,
        resetEmbeddedAuth,
        standaloneUrl,
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
            // Runs the popup within this click gesture (popup-blocker safe).
            beginEmbeddedSignIn(returnPath);
        } else {
            closeSignInModal();
            signIn(returnPath);
        }
    }

    function _onReopen() {
        beginEmbeddedSignIn(returnPath);
    }

    function _onFinish() {
        void continueWithStorageAccess();
    }

    function _onOpenTab() {
        window.open(standaloneUrl(returnPath), '_blank', 'noopener');
        _close();
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

    const _busy = ['finishing'];
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
            {#if embedded && phase === 'awaiting'}
                <h2 id="sign-in-title" class="sign-in-title">Continue in the sign-in window</h2>
                <p class="sign-in-body">
                    A Hugging Face sign-in window has opened. Complete sign-in
                    there and this will update automatically.
                </p>
                <div class="sign-in-actions">
                    <button type="button" class="sign-in-cta" on:click={_onReopen}>
                        Reopen sign-in window
                    </button>
                    <button type="button" class="sign-in-dismiss" on:click={_close}>Cancel</button>
                </div>
            {:else if embedded && phase === 'finishing'}
                <h2 id="sign-in-title" class="sign-in-title">Finishing sign-in…</h2>
                <p class="sign-in-body">One moment.</p>
            {:else if embedded && phase === 'needs-continue'}
                <h2 id="sign-in-title" class="sign-in-title">Almost there</h2>
                <p class="sign-in-body">
                    Click continue to finish signing in inside this embedded view.
                </p>
                <div class="sign-in-actions">
                    <button type="button" class="sign-in-cta" on:click={_onFinish}>Continue</button>
                    <button type="button" class="sign-in-dismiss" on:click={_close}>Cancel</button>
                </div>
            {:else if embedded && phase === 'fallback'}
                <h2 id="sign-in-title" class="sign-in-title">Open in its own tab</h2>
                <p class="sign-in-body">
                    This browser blocks sign-in inside the embedded view. Open the
                    app in its own tab to sign in there — everything works the same.
                </p>
                <div class="sign-in-actions">
                    <button type="button" class="sign-in-cta" on:click={_onOpenTab}>
                        Open app in a new tab
                    </button>
                    <button type="button" class="sign-in-dismiss" on:click={_close}>Cancel</button>
                </div>
            {:else}
                <h2 id="sign-in-title" class="sign-in-title">{title}</h2>
                <p class="sign-in-body">{body}</p>
                <div class="sign-in-actions">
                    <button
                        type="button"
                        class="sign-in-cta"
                        disabled={_busy.includes(phase)}
                        on:click={_onContinue}
                    >
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
    .sign-in-cta:disabled {
        opacity: 0.6;
        cursor: default;
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
