<script lang="ts">
    import { onMount } from 'svelte';

    import { signIn, signOut } from './lib/api/auth-client';
    import DevRoleSwitcher from './lib/components/DevRoleSwitcher.svelte';
    import EditAffordancePopover from './lib/components/EditAffordancePopover.svelte';
    import SignInModal from './lib/components/SignInModal.svelte';
    import ToastHost from './lib/components/ToastHost.svelte';
    import { dashPort } from './lib/playback/dash-port';
    import { loadQuranRefs } from './lib/refs/quran-refs';
    import { currentUser, isSignedIn, loadCurrentUser } from './lib/stores/current-user';
    import { getActiveTab, setActiveTab } from './lib/utils/active-tab';
    import { LS_KEYS, TAB_NAMES } from './lib/utils/constants';
    import DashboardTab from './tabs/dashboard/DashboardTab.svelte';
    import SegmentsTab from './tabs/segments/SegmentsTab.svelte';
    import { segPort } from './tabs/segments/stores/playback';
    import { tsPort } from './tabs/timestamps/stores/playback';
    import TimestampsTab from './tabs/timestamps/TimestampsTab.svelte';

    let activeTab = getActiveTab();

    function _onSignIn() {
        signIn();
    }

    function _onSignOut() {
        void signOut();
    }

    function switchTab(tab: string): void {
        setActiveTab(tab);
        activeTab = tab;
        localStorage.setItem(LS_KEYS.ACTIVE_TAB, tab);
        // Pause whichever tabs the user is leaving. Each tab's port owns
        // its element + transport; pause is no-op when nothing's playing.
        if (tab !== TAB_NAMES.TIMESTAMPS) tsPort.pause();
        if (tab !== TAB_NAMES.SEGMENTS) segPort.pause();
        if (tab !== TAB_NAMES.DASHBOARD) dashPort.pause();
    }

    function cleanupLegacyAudioKeys(): void {
        // Phase 6 removes the Audio tab. Sweep any legacy insp_aud_* keys
        // so they don't linger and confuse future feature work.
        for (let i = localStorage.length - 1; i >= 0; i -= 1) {
            const k = localStorage.key(i);
            if (k && k.startsWith('insp_aud_')) localStorage.removeItem(k);
        }
    }

    onMount(() => {
        cleanupLegacyAudioKeys();
        // Quran refs (dk_words + verse_word_counts) live behind one immutable
        // static asset — fire-and-forget; tabs tolerate the null pre-hydration.
        void loadQuranRefs();
        const savedTab = localStorage.getItem(LS_KEYS.ACTIVE_TAB);
        const validTabs: string[] = [
            TAB_NAMES.DASHBOARD,
            TAB_NAMES.TIMESTAMPS,
            TAB_NAMES.SEGMENTS,
        ];
        if (savedTab && validTabs.includes(savedTab)) {
            switchTab(savedTab);
        } else {
            // First-time visitors and legacy `insp_active_tab='audio'`
            // users land on Dashboard.
            switchTab(TAB_NAMES.DASHBOARD);
        }
        void loadCurrentUser();
    });
</script>

<div class="container">
    <header>
        <div class="tab-bar">
            <button class="tab-btn" class:active={activeTab === TAB_NAMES.DASHBOARD} data-tab={TAB_NAMES.DASHBOARD} on:click={() => switchTab(TAB_NAMES.DASHBOARD)}>Dashboard</button>
            <button class="tab-btn" class:active={activeTab === TAB_NAMES.TIMESTAMPS} data-tab={TAB_NAMES.TIMESTAMPS} on:click={() => switchTab(TAB_NAMES.TIMESTAMPS)}>Timestamps</button>
            <button class="tab-btn" class:active={activeTab === TAB_NAMES.SEGMENTS} data-tab={TAB_NAMES.SEGMENTS} on:click={() => switchTab(TAB_NAMES.SEGMENTS)}>Segments</button>
        </div>
        <div class="auth-controls">
            {#if $currentUser.dev_mode}
                <!-- Local dev only — never rendered on the deployed Space. -->
                <DevRoleSwitcher />
            {:else if isSignedIn($currentUser)}
                <span class="auth-login" title="Signed in as {$currentUser.login}">
                    {$currentUser.login}
                    {#if $currentUser.role && $currentUser.role !== 'contributor'}
                        <span class="auth-role">·{$currentUser.role}</span>
                    {/if}
                </span>
                <button type="button" class="auth-btn" on:click={_onSignOut}>Sign out</button>
            {:else}
                <button type="button" class="auth-btn auth-btn--cta" on:click={_onSignIn}>
                    Sign in with HF
                </button>
            {/if}
        </div>
    </header>

    <!-- ============ Dashboard Tab ============ -->
    <div hidden={activeTab !== TAB_NAMES.DASHBOARD}>
        <DashboardTab />
    </div>

    <!-- ============ Timestamps Tab ============ -->
    <div hidden={activeTab !== TAB_NAMES.TIMESTAMPS}>
        <TimestampsTab />
    </div>

    <!-- ============ Segments Tab ============ -->
    <div hidden={activeTab !== TAB_NAMES.SEGMENTS}>
        <SegmentsTab />
    </div>


</div>

<!-- Single global popover surfaced by `editGate` for non-editor clicks
     on edit affordances. -->
<EditAffordancePopover />

<!-- Root-mounted sign-in modal + toast host (Phase 3). -->
<SignInModal />
<ToastHost />

<style>
    header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        flex-wrap: wrap;
    }
    .tab-bar {
        display: flex;
        align-items: center;
        gap: 0;
    }
    .auth-controls {
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .auth-login {
        font-size: 0.92rem;
        color: #ccc;
    }
    .auth-role {
        margin-left: 4px;
        font-weight: 600;
        color: #8ab4f8;
        text-transform: capitalize;
    }
    .auth-btn {
        border: 1px solid #333;
        background: #16213e;
        color: #ccc;
        padding: 6px 12px;
        border-radius: 6px;
        cursor: pointer;
        font-size: 0.9rem;
        transition: background 0.2s, border-color 0.2s, color 0.2s;
    }
    .auth-btn:hover {
        background: #1a2a4e;
        border-color: #4cc9f0;
        color: #4cc9f0;
    }
    .auth-btn--cta {
        background: #f0a500;
        color: #1a1a1a;
        border: 0;
        font-weight: 600;
    }
    .auth-btn--cta:hover {
        background: #ffba2c;
        border-color: transparent;
        color: #1a1a1a;
    }
</style>
