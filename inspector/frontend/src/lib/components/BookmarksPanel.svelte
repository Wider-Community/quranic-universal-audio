<script lang="ts">
    /**
     * BookmarksPanel — slide-in sidebar listing the user's bookmarked verses.
     *
     * Click a bookmark → request the Timestamps tab to load a random published
     * reciter at that verse and autoplay (via `pendingTsNavigation`).
     *
     * Connection: app-local by default (localStorage, seeded examples). The
     * "Connect Quran.Foundation" button starts the real OAuth flow
     * (`/api/qf/login`); in dev mode a stub-connect button exercises the real
     * backend bookmarks proxy without the live login.
     *
     * Svelte 5 runes; auto-subscribes to the writable stores via `$`.
     */
    import { onMount } from 'svelte';

    import { devConnectQf } from '../api/bookmarks-client';
    import {
        bookmarks,
        bookmarksVisible,
        disconnectQf,
        initBookmarks,
        onQfConnected,
        qfConnected,
        qfDev,
        qfLogin,
        removeBookmark,
    } from '../stores/bookmarks';
    import { currentUser } from '../stores/current-user';
    import { pendingTsNavigation } from '../stores/navigation';
    import { setActiveTab } from '../utils/active-tab';
    import { TAB_NAMES } from '../utils/constants';
    import { surahInfoReady, surahOptionText } from '../utils/surah-info';

    // surahInfo loads async; flip `ready` when it lands so labels re-render
    // from bare numbers to full surah names.
    let ready = $state(false);

    onMount(() => {
        void initBookmarks();
        void surahInfoReady.then(() => {
            ready = true;
        });
    });

    function open(surah: number, ayah: number): void {
        pendingTsNavigation.set({ surah, ayah, autoplay: true });
        setActiveTab(TAB_NAMES.TIMESTAMPS);
        bookmarksVisible.set(false);
    }

    function connect(): void {
        if ($currentUser.dev_mode) {
            void devConnectQf()
                .then(() => {
                    qfDev.set(true);
                    return onQfConnected();
                })
                .catch(() => {});
            return;
        }
        const origin = window.location.origin;
        // Embedded in the huggingface.co iframe: top-navigation is sandbox-blocked
        // and popups get coerced, breaking OAuth state/cookies. Open the login in
        // a NEW TAB — a top-level first-party hf.space context where OAuth works.
        // The user completes sign-in and continues in that tab (connected).
        if (window.self !== window.top) {
            window.open(`${origin}/api/qf/login`, '_blank', 'noopener');
            return;
        }
        // Top-level (direct URL): Google-style popup that signals back via
        // postMessage and closes; we then re-read connection status.
        const loginUrl = `${origin}/api/qf/login?popup=1`;
        const w = 500;
        const h = 680;
        const left = window.screenX + Math.max(0, (window.outerWidth - w) / 2);
        const top = window.screenY + Math.max(0, (window.outerHeight - h) / 2);
        const popup = window.open(
            loginUrl,
            'qf_oauth',
            `popup,width=${w},height=${h},left=${left},top=${top}`,
        );
        if (!popup) {
            // Popup blocked — fall back to a full-page redirect (no popup flag,
            // so the callback redirects back into the app rather than showing
            // the self-closing page).
            window.location.href = `${origin}/api/qf/login`;
            return;
        }

        const onMessage = (e: MessageEvent): void => {
            if (e.origin !== window.location.origin) return;
            const data = e.data as { type?: string; status?: string } | null;
            if (!data || data.type !== 'qf-auth') return;
            cleanup();
            if (data.status === 'connected') {
                void onQfConnected();
            }
        };
        const poll = setInterval(() => {
            if (popup.closed) {
                cleanup();
                // Message may have been missed (e.g. popup closed manually) —
                // re-check status to catch a completed login.
                void initBookmarks();
            }
        }, 700);
        function cleanup(): void {
            clearInterval(poll);
            window.removeEventListener('message', onMessage);
        }
        window.addEventListener('message', onMessage);
    }

    function label(surah: number): string {
        return surahOptionText(surah);
    }
</script>

<aside id="bookmarks-panel" class="bookmarks-panel" hidden={!$bookmarksVisible} aria-label="Bookmarks">
    <header class="bm-header">
        <h2>Bookmarks</h2>
        <button class="bm-close" type="button" title="Close" onclick={() => bookmarksVisible.set(false)}>×</button>
    </header>

    <div class="bm-conn">
        {#if $qfConnected}
            <div class="bm-conn-row">
                {#if $qfDev}
                    <span class="bm-conn-dev" title="Local dev stub — NOT a real Quran.Foundation login. No account or token involved.">
                        ⚙ Dev stub (local only)
                    </span>
                {:else}
                    <span class="bm-conn-on" title="Synced with Quran.Foundation">
                        ● Synced{$qfLogin ? ` · ${$qfLogin}` : ''}
                    </span>
                {/if}
                <button class="bm-disconnect" type="button" onclick={() => disconnectQf()}>
                    Disconnect
                </button>
            </div>
        {:else}
            <button class="bm-connect" type="button" onclick={connect}>
                Connect Quran.Foundation
            </button>
            <p class="bm-conn-hint">Saved locally. Connect to sync across Quran.com apps.</p>
        {/if}
    </div>

    {#if $bookmarks.length === 0}
        <p class="bm-empty">No bookmarks yet. Open a verse in Timestamps and tap ☆ to save it.</p>
    {:else}
        <ul class="bm-list">
            {#each $bookmarks as b (b.key)}
                <li class="bm-item">
                    <button class="bm-open" type="button" onclick={() => open(b.surah, b.ayah)}>
                        <span class="bm-verse">{ready ? label(b.surah) : `Surah ${b.surah}`}</span>
                        <span class="bm-ayah">Ayah {b.ayah}</span>
                    </button>
                    <button
                        class="bm-remove"
                        type="button"
                        title="Remove bookmark"
                        onclick={() => removeBookmark(b.key)}
                    >×</button>
                </li>
            {/each}
        </ul>
    {/if}
</aside>

<style>
    .bookmarks-panel {
        position: fixed;
        top: 0;
        right: 0;
        width: 340px;
        max-width: 90vw;
        height: 100vh;
        background: #0f1530;
        border-left: 1px solid #2a3a6a;
        box-shadow: -8px 0 24px rgba(0, 0, 0, 0.45);
        z-index: 1000;
        display: flex;
        flex-direction: column;
        padding: 16px;
        overflow-y: auto;
        color: #d8def0;
    }
    .bm-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 12px;
    }
    .bm-header h2 {
        font-size: 1.1rem;
        margin: 0;
        color: #fff;
    }
    .bm-close {
        background: none;
        border: 0;
        color: #9aa6c8;
        font-size: 1.5rem;
        line-height: 1;
        cursor: pointer;
    }
    .bm-close:hover { color: #fff; }
    .bm-conn { margin-bottom: 14px; }
    .bm-conn-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .bm-conn-on { color: #5fd38a; font-size: 0.85rem; font-weight: 600; }
    .bm-conn-dev { color: #d8a13a; font-size: 0.85rem; font-weight: 600; }
    .bm-disconnect {
        background: none;
        border: 1px solid #3a3a5a;
        color: #9aa6c8;
        border-radius: 6px;
        padding: 4px 10px;
        font-size: 0.78rem;
        cursor: pointer;
    }
    .bm-disconnect:hover { border-color: #ff6b6b; color: #ff6b6b; }
    .bm-connect {
        width: 100%;
        background: #f0a500;
        color: #1a1a1a;
        border: 0;
        border-radius: 6px;
        padding: 8px 12px;
        font-weight: 600;
        cursor: pointer;
    }
    .bm-connect:hover { background: #ffba2c; }
    .bm-conn-hint { font-size: 0.75rem; color: #8a93b2; margin: 6px 0 0; }
    .bm-empty { font-size: 0.85rem; color: #8a93b2; line-height: 1.5; }
    .bm-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
    .bm-item {
        display: flex;
        align-items: stretch;
        background: #16213e;
        border: 1px solid #25325c;
        border-radius: 8px;
        overflow: hidden;
    }
    .bm-open {
        flex: 1;
        text-align: right;
        background: none;
        border: 0;
        color: #d8def0;
        padding: 10px 12px;
        cursor: pointer;
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    .bm-open:hover { background: #1c294b; }
    .bm-verse { font-size: 0.95rem; color: #fff; }
    .bm-ayah { font-size: 0.78rem; color: #9aa6c8; }
    .bm-remove {
        background: none;
        border: 0;
        border-left: 1px solid #25325c;
        color: #7c87a8;
        font-size: 1.2rem;
        padding: 0 12px;
        cursor: pointer;
    }
    .bm-remove:hover { color: #ff6b6b; background: #1c294b; }
</style>
