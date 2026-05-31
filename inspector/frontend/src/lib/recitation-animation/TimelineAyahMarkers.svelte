<script lang="ts">
    /**
     * Persistent ayah-boundary markers for the player timeline.
     *
     * Absolute-positioned ticks over the progress track, one per ayah start,
     * placed by `startMs / durationMs`. Only the ticks capture pointer events
     * (the container is transparent to them) so the underlying scrubber still
     * drags everywhere between markers. Click a tick to seek to that ayah.
     */
    import { type RecitationAnimConfig } from './config';
    import type { AyahBoundary } from './types';

    interface Props {
        ayahs: AyahBoundary[];
        durationMs: number;
        config: RecitationAnimConfig;
        onSeek: (ms: number) => void;
    }

    let { ayahs, durationMs, config, onSeek }: Props = $props();

    const visible = $derived(config.markersShow && durationMs > 0);

    function pct(ms: number): number {
        return Math.min(100, Math.max(0, (ms / durationMs) * 100));
    }
</script>

{#if visible}
    <div
        class="ra-markers"
        style="--mk-color: {config.markerColor}; --mk-w: {config.markerWidthPx}px; --mk-h: {config.markerHeightPx}px; --mk-op: {config.markerOpacity};"
        aria-hidden="true"
    >
        {#each ayahs as a (a.ayahKey)}
            <button
                type="button"
                class="tick"
                class:labelled={config.markerHoverLabel}
                style="left: {pct(a.startMs)}%;"
                title={config.markerHoverLabel ? `Ayah ${a.surah}:${a.ayah}` : undefined}
                onclick={(e) => {
                    e.stopPropagation();
                    onSeek(a.startMs);
                }}
                onpointerdown={(e) => e.stopPropagation()}
            >
                {#if config.markerHoverLabel}<span class="lbl">{a.surah}:{a.ayah}</span>{/if}
            </button>
        {/each}
    </div>
{/if}

<style>
    .ra-markers {
        position: absolute;
        inset: 0;
        pointer-events: none;
        z-index: 2;
    }
    .tick {
        position: absolute;
        top: 50%;
        transform: translate(-50%, -50%);
        width: var(--mk-w);
        height: var(--mk-h);
        background: var(--mk-color);
        opacity: var(--mk-op);
        border-radius: 1px;
        pointer-events: auto;
        cursor: pointer;
        transition:
            opacity var(--t-fast),
            height var(--t-fast);
    }
    .tick:hover,
    .tick:focus-visible {
        opacity: 1;
        height: calc(var(--mk-h) + 4px);
    }
    .lbl {
        position: absolute;
        bottom: calc(100% + 4px);
        left: 50%;
        transform: translateX(-50%);
        padding: 2px 5px;
        font-family: var(--font-mono);
        font-size: 10px;
        line-height: 1;
        white-space: nowrap;
        color: var(--text-primary);
        background: var(--elevated);
        border: 1px solid var(--border-default);
        border-radius: var(--r-1);
        opacity: 0;
        pointer-events: none;
        transition: opacity var(--t-fast);
    }
    .tick:hover .lbl,
    .tick:focus-visible .lbl {
        opacity: 1;
    }
</style>
