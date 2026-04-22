<script lang="ts">
    import { get } from 'svelte/store';
    import { onMount } from 'svelte';
    import { getActiveTab, setActiveTab } from './lib/utils/active-tab';
    import { LS_KEYS, TAB_NAMES } from './lib/utils/constants';
    import { tsAudioElement } from './tabs/timestamps/stores/playback';
    import { segAudioElement } from './tabs/segments/stores/playback';
    import { audAudioElement } from './tabs/audio/stores/audio';
    import AudioTab from './tabs/audio/AudioTab.svelte';
    import SegmentsTab from './tabs/segments/SegmentsTab.svelte';
    import TimestampsTab from './tabs/timestamps/TimestampsTab.svelte';

    let activeTab = getActiveTab();

    function switchTab(tab: string): void {
        setActiveTab(tab);
        activeTab = tab;
        localStorage.setItem(LS_KEYS.ACTIVE_TAB, tab);
        if (tab !== TAB_NAMES.TIMESTAMPS) {
            get(tsAudioElement)?.pause();
        }
        if (tab !== TAB_NAMES.SEGMENTS) {
            get(segAudioElement)?.pause();
        }
        if (tab !== TAB_NAMES.AUDIO) {
            get(audAudioElement)?.pause();
        }
    }

    onMount(() => {
        const savedTab = localStorage.getItem(LS_KEYS.ACTIVE_TAB);
        const validTabs: string[] = [TAB_NAMES.TIMESTAMPS, TAB_NAMES.SEGMENTS, TAB_NAMES.AUDIO];
        if (savedTab && validTabs.includes(savedTab)) {
            switchTab(savedTab);
        }
    });
</script>

<div class="container">
    <header>
        <h1>Alignment Inspector</h1>
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
