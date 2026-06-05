<script lang="ts">
    import { onDestroy, onMount } from 'svelte';

    import { signIn, signOut } from './lib/api/auth-client';
    import BookmarksPanel from './lib/components/BookmarksPanel.svelte';
    import ClaimConfirmModal from './lib/components/ClaimConfirmModal.svelte';
    import DevRoleSwitcher from './lib/components/DevRoleSwitcher.svelte';
    import EditAffordancePopover from './lib/components/EditAffordancePopover.svelte';
    import ExternalLinks from './lib/components/ExternalLinks.svelte';
    import BottomPlayer from './lib/components/player/BottomPlayer.svelte';
    import InfoModal from './lib/components/info/InfoModal.svelte';
    import SignInModal from './lib/components/SignInModal.svelte';
    import ToastHost from './lib/components/ToastHost.svelte';
    import { dashPort } from './lib/playback/dash-port';
    import { toggleBookmarksPanel } from './lib/stores/bookmarks';
    import { currentUser, isSignedIn, loadCurrentUser } from './lib/stores/current-user';
    import {
        activeTab as activeTabStore,
        getActiveTab,
        setActiveTab,
    } from './lib/utils/active-tab';
    import { LS_KEYS, TAB_NAMES } from './lib/utils/constants';
    import DashboardTab from './tabs/dashboard/DashboardTab.svelte';
    import {
        dashboardState,
        setFilterDrawer,
        setActivityDrawer,
    } from './tabs/dashboard/stores/dashboard-state';
    import SegmentsTab from './tabs/segments/SegmentsTab.svelte';
    import { segPort } from './tabs/segments/stores/playback';
    import { tsPort } from './tabs/timestamps/stores/playback';
    import TimestampsTab from './tabs/timestamps/TimestampsTab.svelte';
    import { allGuidesRead } from './tabs/segments/guides/registry';
    import EditingGuideTab from './tabs/guide/EditingGuideTab.svelte';

    // `activeTab` follows the shared store so external navigation (e.g. the
    // Bookmarks sidebar calling setActiveTab) switches tabs here too.
    let activeTab = getActiveTab();
    const unsubActiveTab = activeTabStore.subscribe((value) => {
        activeTab = value;
    });
    onDestroy(unsubActiveTab);

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
        // Pause dashboard audio when leaving Dashboard — the player is now
        // hidden on every other tab.
        if (tab !== TAB_NAMES.DASHBOARD) dashPort.pause();
        if (tab !== TAB_NAMES.DASHBOARD) {
            setFilterDrawer(false);
            setActivityDrawer(false);
        }
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
        const validTabs: string[] = [TAB_NAMES.DASHBOARD, TAB_NAMES.TIMESTAMPS, TAB_NAMES.SEGMENTS, TAB_NAMES.GUIDE];
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

    let showHeader = true;
    let lastScrollY = 0;

    function handleScroll(): void {
        const scrollY = window.scrollY;
        // Don't hide if near the top
        if (scrollY < 60) {
            showHeader = true;
        } else {
            // Scroll down -> hide, scroll up -> show
            if (scrollY > lastScrollY) {
                showHeader = false;
            } else {
                showHeader = true;
            }
        }
        lastScrollY = scrollY;
    }
</script>

<svelte:window on:scroll={handleScroll} />

<div class="container">
    <header
        id="header"
        class="header"
        class:has-dash-controls={activeTab === TAB_NAMES.DASHBOARD}
        class:header--hidden={!showHeader}
    >
        <div class="header-left">
            <!-- Mobile-only filter toggle: shows left drawer -->
            {#if activeTab === TAB_NAMES.DASHBOARD}
                <button
                    class="icon-btn filter-btn"
                    id="openLeft"
                    aria-label="Filters"
                    on:click={() => setFilterDrawer(true)}
                >
                    <svg
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                    >
                        <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
                    </svg>
                </button>
            {/if}
            <ExternalLinks />
        </div>

        <div class="header-center">
            <nav class="tab-bar" id="tabs">
                <button
                    class="tab-btn"
                    class:active={activeTab === TAB_NAMES.DASHBOARD}
                    data-tab={TAB_NAMES.DASHBOARD}
                    on:click={() => setActiveTab(TAB_NAMES.DASHBOARD)}
                >
                    <svg
                        class="tab-icon"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                    >
                        <rect x="3" y="3" width="7" height="9" />
                        <rect x="14" y="3" width="7" height="5" />
                        <rect x="14" y="12" width="7" height="9" />
                        <rect x="3" y="16" width="7" height="5" />
                    </svg>
                    <span class="tab-label">Dashboard</span>
                </button>
                <button
                    class="tab-btn"
                    class:active={activeTab === TAB_NAMES.TIMESTAMPS}
                    data-tab={TAB_NAMES.TIMESTAMPS}
                    on:click={() => setActiveTab(TAB_NAMES.TIMESTAMPS)}
                >
                    <svg
                        class="tab-icon"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                    >
                        <circle cx="12" cy="12" r="10" />
                        <polyline points="12 6 12 12 16 14" />
                    </svg>
                    <span class="tab-label">Timestamps</span>
                </button>
                <button
                    class="tab-btn"
                    class:active={activeTab === TAB_NAMES.SEGMENTS}
                    data-tab={TAB_NAMES.SEGMENTS}
                    on:click={() => setActiveTab(TAB_NAMES.SEGMENTS)}
                >
                    <svg
                        class="tab-icon"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                    >
                        <path d="M3 10L3 14M7 6L7 18M11 3L11 21M15 8L15 16M19 11L19 13" />
                    </svg>
                    <span class="tab-label">Segments</span>
                </button>
                <button
                    class="tab-btn"
                    class:active={activeTab === TAB_NAMES.GUIDE}
                    class:unread={$currentUser.hf_user_id != null
                        && !allGuidesRead($currentUser.guides_read)}
                    data-tab={TAB_NAMES.GUIDE}
                    on:click={() => setActiveTab(TAB_NAMES.GUIDE)}
                >
                    <svg
                        class="tab-icon"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                    >
                        <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
                        <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
                    </svg>
                    <span class="tab-label">Editing guide</span>
                    {#if $currentUser.hf_user_id != null && !allGuidesRead($currentUser.guides_read)}
                        <span class="tab-unread-dot" aria-label="Unread guides"></span>
                    {/if}
                </button>
            </nav>
        </div>

        <div class="header-right">
            <div class="auth-controls">
                <button
                    type="button"
                    class="auth-btn favorite-btn"
                    id="favoriteBtn"
                    title="Bookmarks"
                    on:click={toggleBookmarksPanel}
                >
                    <svg
                        viewBox="0 0 24 24"
                        width="13"
                        height="13"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                    >
                        <polygon
                            points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"
                        />
                    </svg>
                    <span class="bm-label">Bookmarks</span>
                </button>
                <!-- Mobile-only activity drawer toggle -->
                {#if activeTab === TAB_NAMES.DASHBOARD}
                    <button
                        class="icon-btn icon-only-mobile"
                        aria-label="Activity"
                        id="openRight"
                        on:click={() => setActivityDrawer(true)}
                    >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
                        </svg>
                    </button>
                {/if}
                <div class="header-user">
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
                        <button type="button" class="auth-btn" on:click={_onSignOut}
                            >Sign out</button
                        >
                    {:else}
                        <button type="button" class="auth-btn auth-btn--cta" on:click={_onSignIn}>
                            Sign in with HF
                        </button>
                    {/if}
                </div>
            </div>
        </div>
    </header>

    <!-- ============ Dashboard Tab ============ -->
    {#if mountedTabs.has(TAB_NAMES.DASHBOARD)}
        <div class="tab-panel" hidden={activeTab !== TAB_NAMES.DASHBOARD}>
            <DashboardTab />
        </div>
    {/if}

    <!-- ============ Timestamps Tab ============ -->
    {#if mountedTabs.has(TAB_NAMES.TIMESTAMPS)}
        <div class="tab-panel" hidden={activeTab !== TAB_NAMES.TIMESTAMPS}>
            <TimestampsTab />
        </div>
    {/if}

    <!-- ============ Segments Tab ============ -->
    {#if mountedTabs.has(TAB_NAMES.SEGMENTS)}
        <div class="tab-panel" hidden={activeTab !== TAB_NAMES.SEGMENTS}>
            <SegmentsTab />
        </div>
    {/if}

    <!-- ============ Editing Guide Tab ============ -->
    {#if mountedTabs.has(TAB_NAMES.GUIDE)}
        <div class="tab-panel" hidden={activeTab !== TAB_NAMES.GUIDE}>
            <EditingGuideTab />
        </div>
    {/if}
</div>

<!-- BottomPlayer is only needed on the Dashboard tab.
     Segments has its own SegmentsFooter with a full player;
     Timestamps has no playback surface. -->
<div hidden={activeTab !== TAB_NAMES.DASHBOARD}>
    <BottomPlayer />
</div>

<!-- Single global popover surfaced by `editGate` for non-editor clicks
     on edit affordances. -->
<EditAffordancePopover />

<!-- Root-mounted sign-in modal + toast host (Phase 3). -->
<SignInModal />
<ClaimConfirmModal />
<ToastHost />

<!-- Project-overview modal — opened from the dashboard ⓘ and the segments
     guides gate; single host so it looks identical everywhere. -->
<InfoModal />

<!-- Quran.Foundation bookmarks sidebar. -->
<BookmarksPanel />

<style>
    /* ── Desktop header ── */
    .header {
        height: var(--header-h, 76px);
        display: grid;
        grid-template-columns: 1fr auto 1fr;
        align-items: center;
        padding: 0 16px;
        position: sticky;
        top: 0;
        z-index: 50;
        background: rgba(10, 16, 32, 0.95);
        backdrop-filter: blur(8px);
        border-bottom: 1px solid var(--border-quiet);
        margin-bottom: 0;
        transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .header-left {
        display: flex;
        align-items: center;
        gap: 4px;
        justify-self: start;
    }
    .header-center {
        justify-self: center;
        align-self: stretch;
        display: flex;
        align-items: flex-end;
    }
    .header-right {
        justify-self: end;
    }

    /* Filter btn & activity icon: hidden on desktop, shown on mobile */
    .icon-btn.filter-btn {
        display: none;
    }
    .icon-btn.icon-only-mobile {
        display: none;
    }

    /* icon-btn base style */
    .icon-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 32px;
        height: 32px;
        border-radius: var(--radius-md, 6px);
        background: transparent;
        border: 1px solid var(--border-quiet);
        color: var(--text-secondary);
        cursor: pointer;
        transition:
            background 0.15s,
            border-color 0.15s,
            color 0.15s;
    }
    .icon-btn:hover {
        background: var(--panel-2);
        border-color: var(--border-default);
        color: var(--text-primary);
    }
    .icon-btn svg {
        width: 16px;
        height: 16px;
        display: block;
    }

    .tab-bar {
        display: flex;
        align-items: flex-end;
        gap: 0;
        margin-bottom: -1px;
    }
    .auth-controls {
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .header-user {
        display: flex;
        align-items: center;
        gap: 8px;
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
        transition:
            background 0.2s,
            border-color 0.2s,
            color 0.2s;
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
    /* Bookmarks button: show label on desktop, icon-only on mobile */
    .favorite-btn {
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }

    .tab-panel {
        box-sizing: border-box;
    }

    @media (max-width: 1280px) {
        .icon-btn.icon-only-mobile {
            display: inline-flex;
        }
    }

    /* ── Tablet/Mobile < 900px ── */
    @media (max-width: 899px) {
        .tab-panel {
            padding: 0 12px;
        }
        :global(:root) {
            --header-h: 98px;
        }

        .header {
            grid-template-columns: auto 1fr;
            grid-template-rows: auto auto auto;
            align-items: center;
            gap: 4px 10px;
            height: auto;
            min-height: var(--header-h, 98px);
            padding: 6px 8px;
        }
        .header.has-dash-controls {
            grid-template-columns: auto auto 1fr auto;
        }
        .header.header--hidden {
            transform: translateY(-100%);
        }

        /* Dissolve wrappers so children become direct grid items */
        .header-left,
        .header-center,
        .header-right,
        .auth-controls {
            display: contents;
        }

        /* Row 1 — external links centred across all columns */
        .header-left :global(.link-rail) {
            grid-row: 1;
            grid-column: 1 / -1;
            justify-content: center;
        }

        /* Row 2 — tabs full-width */
        .tab-bar {
            grid-row: 2;
            grid-column: 1 / -1;
            width: 100%;
            margin-bottom: 0;
            align-items: center;
        }

        /* Row 3 — filter | bookmark | activity | user */
        .filter-btn {
            grid-row: 3;
            grid-column: 1;
            display: inline-flex !important;
        }
        .favorite-btn {
            grid-row: 3;
            grid-column: 1;
            width: 32px;
            height: 32px;
            padding: 0;
            justify-content: center;
        }
        .header.has-dash-controls .favorite-btn {
            grid-column: 2;
        }
        .bm-label {
            display: none;
        } /* hide "Bookmarks" label */
        .icon-only-mobile {
            grid-row: 3;
            grid-column: 3;
            display: inline-flex !important;
        }
        .header.has-dash-controls .icon-only-mobile {
            grid-column: 4;
            justify-self: end;
        }
        .header-user {
            grid-row: 3;
            grid-column: 2;
            justify-self: end;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .header.has-dash-controls .header-user {
            grid-column: 3;
            justify-self: center;
        }
    }
</style>
