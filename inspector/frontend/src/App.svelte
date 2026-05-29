<script lang="ts">
    import { onMount } from 'svelte';

    import { signIn, signOut } from './lib/api/auth-client';
    import BookmarksPanel from './lib/components/BookmarksPanel.svelte';
    import DevRoleSwitcher from './lib/components/DevRoleSwitcher.svelte';
    import EditAffordancePopover from './lib/components/EditAffordancePopover.svelte';
    import ExternalLinks from './lib/components/ExternalLinks.svelte';
    import SignInModal from './lib/components/SignInModal.svelte';
    import ToastHost from './lib/components/ToastHost.svelte';
    import { dashPort } from './lib/playback/dash-port';
    import { toggleBookmarksPanel } from './lib/stores/bookmarks';
    import { currentUser, isSignedIn, loadCurrentUser } from './lib/stores/current-user';
    import { activeTab as activeTabStore, getActiveTab, setActiveTab } from './lib/utils/active-tab';
    import { LS_KEYS, TAB_NAMES } from './lib/utils/constants';
    import DashboardTab from './tabs/dashboard/DashboardTab.svelte';
    import SegmentsTab from './tabs/segments/SegmentsTab.svelte';
    import { segPort } from './tabs/segments/stores/playback';
    import { tsPort } from './tabs/timestamps/stores/playback';
    import TimestampsTab from './tabs/timestamps/TimestampsTab.svelte';

    // `activeTab` follows the shared store so external navigation (e.g. the
    // Bookmarks sidebar calling setActiveTab) switches tabs here too.
    let activeTab = getActiveTab();
    $: activeTab = $activeTabStore;
    // Lazy-mount tabs: defer Timestamps/Segments mount until the user actually
    // visits them. Once visited, the tab stays in the DOM (hidden) so its
    // state (loaded reciter, scroll position, edits) survives tab switches.
    // Dashboard-only visitors avoid the cold-load shard prefetch, segment-peaks
    // POST, quran-refs.json, etc.
    let mountedTabs = new Set<string>([activeTab]);
    $: if (activeTab && !mountedTabs.has(activeTab)) {
        mountedTabs = new Set([...mountedTabs, activeTab]);
    }
    // Tab side-effects run on every change — whether triggered by a tab-bar
    // button or external setActiveTab. Persist the choice and pause the ports
    // of the tabs being left (pause is a no-op when nothing's playing).
    $: applyTabSideEffects(activeTab);

    function applyTabSideEffects(tab: string): void {
        if (!tab) return;
        localStorage.setItem(LS_KEYS.ACTIVE_TAB, tab);
        if (tab !== TAB_NAMES.TIMESTAMPS) tsPort.pause();
        if (tab !== TAB_NAMES.SEGMENTS) segPort.pause();
        if (tab !== TAB_NAMES.DASHBOARD) dashPort.pause();
    }

    function _onSignIn() {
        signIn();
    }

    function _onSignOut() {
        void signOut();
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
        // Quran refs (dk_words + verse_word_counts) is a 2.4 MB decoded
        // bundle used only by the Segments tab. Deferred to SegmentsTab's
        // onMount so Dashboard/Timestamps-only visitors don't pay the cost.
        const savedTab = localStorage.getItem(LS_KEYS.ACTIVE_TAB);
        const validTabs: string[] = [
            TAB_NAMES.DASHBOARD,
            TAB_NAMES.TIMESTAMPS,
            TAB_NAMES.SEGMENTS,
        ];
        if (savedTab && validTabs.includes(savedTab)) {
            setActiveTab(savedTab);
        } else {
            // First-time visitors and legacy `insp_active_tab='audio'`
            // users land on Dashboard.
            setActiveTab(TAB_NAMES.DASHBOARD);
        }
        void loadCurrentUser();

        // Re-resolve identity + capabilities when the tab regains focus, so an
        // owner's permission toggle (and role changes) reflect in the UI
        // without a manual reload — the backend already enforces immediately;
        // this keeps the affordances in sync for an idle, already-loaded user.
        const onVisible = (): void => {
            if (document.visibilityState === 'visible') void loadCurrentUser();
        };
        document.addEventListener('visibilitychange', onVisible);
        return () => document.removeEventListener('visibilitychange', onVisible);
    });
</script>

<div class="container">
    <header>
        <ExternalLinks />
        <div class="tab-bar">
            <button class="tab-btn" class:active={activeTab === TAB_NAMES.DASHBOARD} data-tab={TAB_NAMES.DASHBOARD} on:click={() => setActiveTab(TAB_NAMES.DASHBOARD)}>Dashboard</button>
            <button class="tab-btn" class:active={activeTab === TAB_NAMES.TIMESTAMPS} data-tab={TAB_NAMES.TIMESTAMPS} on:click={() => setActiveTab(TAB_NAMES.TIMESTAMPS)}>Timestamps</button>
            <button class="tab-btn" class:active={activeTab === TAB_NAMES.SEGMENTS} data-tab={TAB_NAMES.SEGMENTS} on:click={() => setActiveTab(TAB_NAMES.SEGMENTS)}>Segments</button>
        </div>
        <div class="auth-controls">
            <button type="button" class="auth-btn" title="Bookmarks" on:click={toggleBookmarksPanel}>
                ☆ Bookmarks
            </button>
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
    {#if mountedTabs.has(TAB_NAMES.DASHBOARD)}
        <div hidden={activeTab !== TAB_NAMES.DASHBOARD}>
            <DashboardTab />
        </div>
    {/if}

    <!-- ============ Timestamps Tab ============ -->
    {#if mountedTabs.has(TAB_NAMES.TIMESTAMPS)}
        <div hidden={activeTab !== TAB_NAMES.TIMESTAMPS}>
            <TimestampsTab />
        </div>
    {/if}

    <!-- ============ Segments Tab ============ -->
    {#if mountedTabs.has(TAB_NAMES.SEGMENTS)}
        <div hidden={activeTab !== TAB_NAMES.SEGMENTS}>
            <SegmentsTab />
        </div>
    {/if}


</div>

<!-- Single global popover surfaced by `editGate` for non-editor clicks
     on edit affordances. -->
<EditAffordancePopover />

<!-- Root-mounted sign-in modal + toast host (Phase 3). -->
<SignInModal />
<ToastHost />

<!-- Quran.Foundation bookmarks sidebar. -->
<BookmarksPanel />

<style>
    header {
        display: grid;
        grid-template-columns: 1fr auto 1fr;
        align-items: center;
        gap: 12px;
    }
    .tab-bar {
        display: flex;
        align-items: center;
        gap: 0;
        grid-column: 2;
        justify-self: center;
    }
    .auth-controls {
        display: flex;
        align-items: center;
        gap: 10px;
        grid-column: 3;
        justify-self: end;
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
