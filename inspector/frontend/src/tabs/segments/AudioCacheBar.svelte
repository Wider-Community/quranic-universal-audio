<script lang="ts">
    import { get } from 'svelte/store';

    import {
        cacheStatus,
        cacheStatusText,
        cacheProgress,
        cachePrepareButton,
        cacheDeleteButton,
    } from '../../lib/stores/segments/audio-cache';
    import { _prepareAudio, _deleteAudioCache } from '../../lib/utils/segments/audio-cache-ui';
    import { selectedReciter } from '../../lib/stores/segments/chapter';

    function onPrepareClick(): void { _prepareAudio(get(selectedReciter)); }
    function onDeleteClick(): void { _deleteAudioCache(get(selectedReciter)); }
</script>

{#if $cacheStatus !== 'hidden'}
    <div class="seg-cache-panel" id="seg-cache-bar">
        <div class="seg-cache-actions">
            <button
                id="seg-prepare-btn"
                class="btn seg-cache-download-btn"
                hidden={$cachePrepareButton.hidden}
                disabled={$cachePrepareButton.disabled}
                on:click={onPrepareClick}
            >{$cachePrepareButton.label}</button>
            <button
                id="seg-delete-cache-btn"
                class="btn seg-cache-delete-btn"
                hidden={$cacheDeleteButton.hidden}
                disabled={$cacheDeleteButton.disabled}
                on:click={onDeleteClick}
            >{$cacheDeleteButton.label}</button>
        </div>
        {#if $cacheProgress}
            <div id="seg-cache-progress" class="seg-cache-progress">
                <div class="seg-cache-progress-bar">
                    <div
                        id="seg-cache-progress-fill"
                        class="seg-cache-progress-fill"
                        style:width={$cacheProgress.pct + '%'}
                    ></div>
                </div>
                <span id="seg-cache-progress-text" class="seg-cache-progress-text">{$cacheProgress.text}</span>
            </div>
        {/if}
        <span id="seg-cache-status" class="seg-cache-status">{$cacheStatusText}</span>
    </div>
{/if}
