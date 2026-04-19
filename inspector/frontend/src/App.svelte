<script lang="ts">
    import { get } from 'svelte/store';
    import { onMount } from 'svelte';
    import { getActiveTab, setActiveTab } from './lib/utils/active-tab';
    import { LS_KEYS } from './lib/utils/constants';
    import { tsAudioElement } from './tabs/timestamps/stores/playback';
    import { segAudioElement } from './tabs/segments/stores/playback';
    import { audAudioElement } from './tabs/audio/stores/audio';
    import { stopErrorCardAudio } from './tabs/segments/utils/playback/error-card-audio';
    import AudioTab from './tabs/audio/AudioTab.svelte';
    import SegmentsTab from './tabs/segments/SegmentsTab.svelte';
    import TimestampsTab from './tabs/timestamps/TimestampsTab.svelte';

    let activeTab = getActiveTab();

    function switchTab(tab: string): void {
        setActiveTab(tab);
        activeTab = tab;
        localStorage.setItem(LS_KEYS.ACTIVE_TAB, tab);
        if (tab !== 'timestamps') {
            get(tsAudioElement)?.pause();
        }
        if (tab !== 'segments') {
            get(segAudioElement)?.pause();
            stopErrorCardAudio();
        }
        if (tab !== 'audio') {
            get(audAudioElement)?.pause();
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
    <div hidden={activeTab !== 'segments'}>
        <SegmentsTab />
    </div>

    <!-- ============ Audio Tab ============ -->
    <div hidden={activeTab !== 'audio'}>
        <AudioTab />
    </div>

</div>
