<!--
    Sign-in modal. Mounted once at the app root and surfaced via
    `openSignInModal()` whenever an anonymous user attempts a
    contribution action (claim, save, etc.).
-->
<script lang="ts">
    import { signIn } from '../api/auth-client';
    import { closeSignInModal, signInModal } from '../stores/sign-in-modal';

    $: title = $signInModal.context?.title ?? 'Sign in to contribute';
    $: body = $signInModal.context?.body ?? 'Sign in with your Hugging Face account to claim a reciter and edit segments. We only read your username and avatar — nothing else.';

    function _onContinue() {
        const returnPath = $signInModal.returnPath ?? '/';
        closeSignInModal();
        signIn(returnPath);
    }

    function _onBackdropClick(e: MouseEvent) {
        if (e.target === e.currentTarget) closeSignInModal();
    }

    function _onKeydown(e: KeyboardEvent) {
        if (e.key === 'Escape') closeSignInModal();
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
            <h2 id="sign-in-title" class="sign-in-title">{title}</h2>
            <p class="sign-in-body">{body}</p>
            <div class="sign-in-actions">
                <button type="button" class="sign-in-cta" on:click={_onContinue}>
                    Continue with Hugging Face
                </button>
                <button
                    type="button"
                    class="sign-in-dismiss"
                    on:click={closeSignInModal}
                >
                    Cancel
                </button>
            </div>
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
