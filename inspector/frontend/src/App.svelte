<script lang="ts">
    import { onMount } from 'svelte';
    import { getActiveTab, setActiveTab } from './lib/utils/active-tab';
    import { LS_KEYS } from './lib/utils/constants';
    import SegmentsTab from './tabs/segments/SegmentsTab.svelte';
    import TimestampsTab from './tabs/timestamps/TimestampsTab.svelte';

    let activeTab = getActiveTab();

    function switchTab(tab: string): void {
        setActiveTab(tab);
        activeTab = tab;
        localStorage.setItem(LS_KEYS.ACTIVE_TAB, tab);
        // Pause audio from other tabs to avoid multiple streams playing
        if (tab !== 'timestamps') {
            const tsAudio = document.getElementById('audio-player') as HTMLAudioElement | null;
            if (tsAudio) tsAudio.pause();
        }
        if (tab !== 'segments') {
            const segAudio = document.getElementById('seg-audio-player') as HTMLAudioElement | null;
            if (segAudio) segAudio.pause();
            const segPanel = document.getElementById('segments-panel');
            if (segPanel) {
                segPanel.querySelectorAll<HTMLAudioElement>('audio').forEach(a => {
                    if (a.id !== 'seg-audio-player') a.pause();
                });
            }
        }
        if (tab !== 'audio') {
            const audPlayer = document.getElementById('aud-player') as HTMLAudioElement | null;
            if (audPlayer) audPlayer.pause();
        }
    }

    onMount(() => {
        const savedTab = localStorage.getItem(LS_KEYS.ACTIVE_TAB);
        if (savedTab && ['timestamps', 'segments', 'audio'].includes(savedTab)) {
            switchTab(savedTab);
        }
    });
</script>

<div class="container">
    <header>
        <h1>Alignment Inspector</h1>
        <p class="header-links">Want to add a reciter? <a href="https://huggingface.co/spaces/hetchyy/Quran-reciter-requests" target="_blank" rel="noopener">Submit a request</a></p>
        <div class="tab-bar">
            <button class="tab-btn" class:active={activeTab === 'timestamps'} data-tab="timestamps" on:click={() => switchTab('timestamps')}>Timestamps</button>
            <button class="tab-btn" class:active={activeTab === 'segments'} data-tab="segments" on:click={() => switchTab('segments')}>Segments</button>
            <button class="tab-btn" class:active={activeTab === 'audio'} data-tab="audio" on:click={() => switchTab('audio')}>Audio</button>
        </div>
    </header>

    <!-- ============ Timestamps Tab ============ -->
    <div hidden={activeTab !== 'timestamps'}>
        <TimestampsTab />
    </div>

    <!-- ============ Segments Tab ============ -->
    <div id="segments-panel" hidden={activeTab !== 'segments'}>
        <SegmentsTab />
    </div>

    <!-- ============ Audio Tab ============ -->
    <div id="audio-panel" hidden={activeTab !== 'audio'}>
        <div class="info-bar">
            <div class="ts-view-toggle" id="aud-category-toggle">
                <button class="ts-view-btn active" data-cat="by_surah">By Surah</button>
                <button class="ts-view-btn" data-cat="by_ayah">By Ayah</button>
            </div>
            <label>Reciter:
                <select id="aud-reciter-select"><option value="">Loading...</option></select>
            </label>
            <label>Surah:
                <select id="aud-surah-select"><option value="">--</option></select>
            </label>
            <label id="aud-ayah-label" hidden>Ayah:
                <select id="aud-ayah-select"><option value="">--</option></select>
            </label>
        </div>
        <div class="audio-controls">
            <button id="aud-prev-btn" class="btn btn-nav" disabled title="Previous">&#9664; Prev</button>
            <audio id="aud-player" controls preload="none"></audio>
            <button id="aud-next-btn" class="btn btn-nav" disabled title="Next">Next &#9654;</button>
        </div>
    </div>

</div>
