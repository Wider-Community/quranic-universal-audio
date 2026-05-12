<!--
    Sign-in modal. Mounted once at the app root and surfaced via
    `openSignInModal()` whenever an anonymous user attempts a
    contribution action (claim, save, etc.).
-->
<script lang="ts">
    import { signIn } from '../api/auth-client';
    import { closeSignInModal, signInModal } from '../stores/sign-in-modal';

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
            <h2 id="sign-in-title" class="sign-in-title">Sign in to contribute</h2>
            <p class="sign-in-body">
                Sign in with your Hugging Face account to claim a reciter and edit
                segments. We only read your username and avatar — nothing else.
            </p>
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
