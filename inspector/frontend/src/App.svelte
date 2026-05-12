<script lang="ts">
    import { onMount } from 'svelte';

    import { signIn, signOut } from './lib/api/auth-client';
    import EditAffordancePopover from './lib/components/EditAffordancePopover.svelte';
    import SignInModal from './lib/components/SignInModal.svelte';
    import ToastHost from './lib/components/ToastHost.svelte';
    import { currentUser, isSignedIn, loadCurrentUser } from './lib/stores/current-user';
    import { getActiveTab, setActiveTab } from './lib/utils/active-tab';
    import { LS_KEYS, TAB_NAMES } from './lib/utils/constants';
    import AudioTab from './tabs/audio/AudioTab.svelte';
    import { audPort } from './tabs/audio/stores/audio';
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
        if (tab !== TAB_NAMES.AUDIO) audPort.pause();
    }

    onMount(() => {
        const savedTab = localStorage.getItem(LS_KEYS.ACTIVE_TAB);
        const validTabs: string[] = [TAB_NAMES.TIMESTAMPS, TAB_NAMES.SEGMENTS, TAB_NAMES.AUDIO];
        if (savedTab && validTabs.includes(savedTab)) {
            switchTab(savedTab);
        }
        void loadCurrentUser();
    });
</script>

<div class="container">
    <header>
        <div class="header-row">
            <h1>Alignment Inspector</h1>
            <div class="auth-controls">
                {#if isSignedIn($currentUser)}
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
        </div>
        <p class="header-links">Want to add a reciter? <a href="https://huggingface.co/spaces/hetchyy/Quran-reciter-requests" target="_blank" rel="noopener">Submit a request</a></p>
        <div class="tab-bar">
            <button class="tab-btn" class:active={activeTab === TAB_NAMES.TIMESTAMPS} data-tab={TAB_NAMES.TIMESTAMPS} on:click={() => switchTab(TAB_NAMES.TIMESTAMPS)}>Timestamps</button>
            <button class="tab-btn" class:active={activeTab === TAB_NAMES.SEGMENTS} data-tab={TAB_NAMES.SEGMENTS} on:click={() => switchTab(TAB_NAMES.SEGMENTS)}>Segments</button>
            <button class="tab-btn" class:active={activeTab === TAB_NAMES.AUDIO} data-tab={TAB_NAMES.AUDIO} on:click={() => switchTab(TAB_NAMES.AUDIO)}>Audio</button>
        </div>
    </header>

    <!-- ============ Timestamps Tab ============ -->
    <div hidden={activeTab !== TAB_NAMES.TIMESTAMPS}>
        <TimestampsTab />
    </div>

    <!-- ============ Segments Tab ============ -->
    <div hidden={activeTab !== TAB_NAMES.SEGMENTS}>
        <SegmentsTab />
    </div>

    <!-- ============ Audio Tab ============ -->
    <div hidden={activeTab !== TAB_NAMES.AUDIO}>
        <AudioTab />
    </div>

</div>

<!-- Single global popover surfaced by `editGate` for non-editor clicks
     on edit affordances. -->
<EditAffordancePopover />

<!-- Root-mounted sign-in modal + toast host (Phase 3). -->
<SignInModal />
<ToastHost />

<style>
    .header-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        flex-wrap: wrap;
    }
    .header-row h1 {
        margin: 0;
    }
    .auth-controls {
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .auth-login {
        font-size: 0.92rem;
        opacity: 0.85;
    }
    .auth-role {
        margin-left: 4px;
        font-weight: 600;
        opacity: 0.75;
        text-transform: capitalize;
    }
    .auth-btn {
        border: 1px solid rgba(0, 0, 0, 0.15);
        background: transparent;
        padding: 6px 12px;
        border-radius: 6px;
        cursor: pointer;
        font-size: 0.9rem;
    }
    .auth-btn:hover {
        border-color: rgba(0, 0, 0, 0.35);
    }
    .auth-btn--cta {
        background: #f0a500;
        color: #1a1a1a;
        border: 0;
        font-weight: 600;
    }
    .auth-btn--cta:hover {
        background: #ffba2c;
    }
</style>
