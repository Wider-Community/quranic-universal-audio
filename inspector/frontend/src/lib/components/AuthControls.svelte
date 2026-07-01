<!--
  AuthControls — the header's account cluster, one cohesive unit across all three
  auth states so it sits nicely beside the theme toggle:
    · dev      → the DevRoleSwitcher (local only)
    · signed in → an identity pill: avatar · name · role, with an integrated
                  sign-out affordance divided off the right (reads as one object,
                  not a floating name + a detached button)
    · anon     → the "Sign in with HF" CTA

  All token-driven and a shared 32px control height so the whole right-hand
  cluster (toggle + this) aligns in both themes.
-->
<script lang="ts">
    import { signIn, signOut } from '../api/auth-client';
    import { currentUser, isSignedIn } from '../stores/current-user';
    import DevRoleSwitcher from './DevRoleSwitcher.svelte';

    const user = $derived($currentUser);
    const initial = $derived(user.login ? user.login.charAt(0).toUpperCase() : '?');
    const showRole = $derived(!!user.role && user.role !== 'contributor');
</script>

{#if user.dev_mode}
    <!-- Local dev only — never rendered on the deployed Space. -->
    <DevRoleSwitcher />
{:else if isSignedIn(user)}
    <div class="identity" title="Signed in as {user.login}">
        <span class="avatar" aria-hidden="true">{initial}</span>
        <span class="name">{user.login}</span>
        {#if showRole}
            <span class="role">{user.role}</span>
        {/if}
        <button type="button" class="signout" title="Sign out" aria-label="Sign out"
                onclick={() => void signOut()}>
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor"
                 stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
        </button>
    </div>
{:else}
    <button type="button" class="signin" onclick={() => signIn()}>
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
            <polyline points="10 17 15 12 10 7" />
            <line x1="15" y1="12" x2="3" y2="12" />
        </svg>
        Sign in with HF
    </button>
{/if}

<style>
    /* ---------- identity pill (signed in) ---------- */
    .identity {
        display: inline-flex;
        align-items: center;
        height: 32px;
        padding-left: 4px;
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-2);
        overflow: hidden;
        max-width: 260px;
    }
    .avatar {
        flex: 0 0 auto;
        width: 24px;
        height: 24px;
        display: grid;
        place-items: center;
        border-radius: 50%;
        background: var(--accent-tint);
        color: var(--accent);
        font-size: 0.72rem;
        font-weight: 700;
        line-height: 1;
        text-transform: uppercase;
    }
    .name {
        padding: 0 8px;
        font-size: 0.85rem;
        font-weight: 500;
        color: var(--text-primary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        min-width: 0;
    }
    .role {
        flex: 0 0 auto;
        margin-right: 8px;
        padding: 2px 7px;
        font-size: 0.6rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        color: var(--role-blue);
        background: color-mix(in oklch, var(--role-blue) 14%, transparent);
        border-radius: var(--r-1);
        white-space: nowrap;
    }
    .signout {
        flex: 0 0 auto;
        align-self: stretch;
        display: grid;
        place-items: center;
        width: 30px;
        padding: 0;
        border: 0;
        border-left: 1px solid var(--border-quiet);
        background: transparent;
        color: var(--text-muted);
        cursor: pointer;
        transition: background var(--t-fast), color var(--t-fast);
    }
    /* The logout glyph's arrow points outward (right), so its bounding box reads
       right-heavy; nudge left a hair to optically centre it in the cell. */
    .signout svg {
        transform: translateX(-1px);
    }
    .signout:hover {
        background: var(--bad-tint);
        color: var(--bad-fg);
    }
    .signout:focus-visible {
        outline: 2px solid var(--accent);
        outline-offset: -2px;
    }

    /* ---------- sign-in CTA (anon) ---------- */
    .signin {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        height: 32px;
        padding: 0 14px;
        border: 0;
        border-radius: var(--r-2);
        background: var(--signin-bg);
        color: var(--signin-fg);
        font-size: 0.85rem;
        font-weight: 600;
        cursor: pointer;
        transition: background var(--t-fast);
    }
    .signin:hover {
        background: var(--signin-bg-hover);
    }
    .signin:focus-visible {
        outline: 2px solid var(--signin-bg);
        outline-offset: 2px;
    }
</style>
