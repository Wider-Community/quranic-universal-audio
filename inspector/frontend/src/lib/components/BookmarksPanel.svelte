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
        recheckConnection,
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
    // Absolute login URL on this app's own origin (always *.hf.space inside the
    // HF iframe). Used as a real anchor href so the browser reliably opens a
    // first-party top-level tab — HF's recommended OAuth-from-Space pattern.
    let loginHref = $state('/api/qf/login');

    onMount(() => {
        loginHref = `${window.location.origin}/api/qf/login`;
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

    /** Dev-mode stub connect (no real OAuth). */
    function devConnect(): void {
        void devConnectQf()
            .then(() => {
                qfDev.set(true);
                return onQfConnected();
            })
            .catch(() => {});
    }

    /** Login opens in a new top-level tab (the `<a target="_blank">`). When the
     *  user returns to this tab, re-check status — on the direct (first-party)
     *  URL that flips us to connected + merges. In the HF iframe the embed can't
     *  read the session (third-party cookies), so the new tab is the home. */
    function armConnect(): void {
        const onFocus = (): void => {
            window.removeEventListener('focus', onFocus);
            void recheckConnection();
        };
        window.addEventListener('focus', onFocus);
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
        {:else if $currentUser.dev_mode}
            <button class="bm-connect" type="button" onclick={devConnect}>
                Connect (dev stub)
            </button>
            <p class="bm-conn-hint">Saved locally. Connect to sync across Quran.com apps.</p>
        {:else}
            <a class="bm-connect" href={loginHref} target="_blank" rel="noopener" onclick={armConnect}>
                Connect Quran.Foundation
            </a>
            <p class="bm-conn-hint">Opens a new tab to sign in. Bookmarks are saved locally until then.</p>
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
        left: 0;
        width: 340px;
        max-width: 90vw;
        height: 100vh;
        background: var(--panel-sidebar);
        border-right: 1px solid var(--border-default);
        box-shadow: var(--shadow-pop);
        z-index: 1000;
        display: flex;
        flex-direction: column;
        padding: 16px;
        overflow-y: auto;
        color: var(--text-secondary);
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
        color: var(--text-primary);
    }
    .bm-close {
        background: none;
        border: 0;
        color: var(--text-secondary);
        font-size: 1.5rem;
        line-height: 1;
        cursor: pointer;
    }
    .bm-close:hover { color: var(--text-primary); }
    .bm-conn { margin-bottom: 14px; }
    .bm-conn-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .bm-conn-on { color: var(--ok-fg); font-size: 0.85rem; font-weight: 600; }
    .bm-conn-dev { color: var(--state-dev-fg); font-size: 0.85rem; font-weight: 600; }
    .bm-disconnect {
        background: none;
        border: 1px solid var(--border-strong);
        color: var(--text-secondary);
        border-radius: 6px;
        padding: 4px 10px;
        font-size: 0.78rem;
        cursor: pointer;
    }
    .bm-disconnect:hover { border-color: var(--bad-fg); color: var(--bad-fg); }
    .bm-connect {
        display: block;
        width: 100%;
        box-sizing: border-box;
        text-align: center;
        text-decoration: none;
        background: var(--cta-bg);
        color: var(--cta-fg);
        border: 0;
        border-radius: 6px;
        padding: 8px 12px;
        font-weight: 600;
        cursor: pointer;
    }
    .bm-connect:hover { background: var(--cta-bg-hover); }
    .bm-conn-hint { font-size: 0.75rem; color: var(--text-muted); margin: 6px 0 0; }
    .bm-empty { font-size: 0.85rem; color: var(--text-muted); line-height: 1.5; }
    .bm-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
    .bm-item {
        display: flex;
        align-items: stretch;
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: 8px;
        overflow: hidden;
    }
    .bm-open {
        flex: 1;
        text-align: right;
        background: none;
        border: 0;
        color: var(--text-secondary);
        padding: 10px 12px;
        cursor: pointer;
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    .bm-open:hover { background: var(--panel-2); }
    .bm-verse { font-size: 0.95rem; color: var(--text-primary); }
    .bm-ayah { font-size: 0.78rem; color: var(--text-secondary); }
    .bm-remove {
        background: none;
        border: 0;
        border-left: 1px solid var(--border-default);
        color: var(--text-muted);
        font-size: 1.2rem;
        padding: 0 12px;
        cursor: pointer;
    }
    .bm-remove:hover { color: var(--bad-fg); background: var(--panel-2); }
</style>
