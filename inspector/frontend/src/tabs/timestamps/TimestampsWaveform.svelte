<script lang="ts">
    /**
     * TimestampsWaveform — waveform + overlays for the Timestamps tab.
     *
     * Wraps <WaveformCanvas> (base peaks rendering) and adds the timestamps-
     * specific overlays (phoneme boundaries, word boundaries, current-word
     * highlight, current-phoneme highlight, playhead) drawn imperatively onto
     * the same canvas. A snapshot of the base waveform is cached after each
     * redraw so per-frame updates only redraw overlays.
     *
     * Click to seek is handled at this level.
     */

    import { afterUpdate, onMount } from 'svelte';
    import { get } from 'svelte/store';

    import WaveformCanvas from '../../lib/components/WaveformCanvas.svelte';
    import { loadedVerse } from '../../lib/stores/timestamps/verse';
    import { tsAudioElement } from '../../lib/stores/timestamps/playback';
    import { computePeaksForSlice, decodeAudioUrl } from '../../lib/utils/webaudio-peaks';
    import type { PeakBucket } from '../../lib/types/domain';
    import { PREVIEW_PLAYHEAD_COLOR } from '../../lib/utils/constants';

    // ---- Sizing ----

    let containerEl: HTMLDivElement;
    let waveformRef: WaveformCanvas;
    let canvasWidth = 1200;
    const canvasHeight = 200;

    // ---- Peaks + snapshot ----

    let peaks: PeakBucket[] | null = null;
    let snapshotCanvas: HTMLCanvasElement | null = null;
    let pendingUrl: string | null = null;
    let decodeGen = 0; // cancellation token for stale async decodes

    // Reactive: decode audio when loaded verse changes
    $: reactToVerse($loadedVerse?.data.audio_url ?? null, $loadedVerse?.tsSegOffset ?? 0, $loadedVerse?.tsSegEnd ?? 0);

    async function reactToVerse(url: string | null, startSec: number, endSec: number): Promise<void> {
        if (!url) {
            peaks = null;
            snapshotCanvas = null;
            return;
        }
        if (pendingUrl === url) {
            // Same URL — may need re-slice if offsets changed; rebuild peaks
            // against the cached buffer via decodeAudioUrl (cache hit is fast).
        }
        pendingUrl = url;
        const gen = ++decodeGen;
        try {
            const buffer = await decodeAudioUrl(url);
            if (gen !== decodeGen) return; // stale
            const effEnd = endSec > startSec ? endSec : buffer.duration;
            peaks = computePeaksForSlice(buffer, startSec, effEnd, canvasWidth || 1200);
        } catch (e) {
            console.error('Waveform decode failed:', e);
            peaks = null;
        }
    }

    // After WaveformCanvas redraws, snapshot the pristine waveform so per-frame
    // overlay draws blit-then-draw without re-running the peak algorithm.
    afterUpdate(() => {
        if (peaks && waveformRef) {
            cacheSnapshot();
            drawOverlays();
        }
    });

    function cacheSnapshot(): void {
        if (!waveformRef) return;
        const base = waveformRef.getCanvas();
        if (!base || !base.width || !base.height) return;
        if (!snapshotCanvas) snapshotCanvas = document.createElement('canvas');
        snapshotCanvas.width = base.width;
        snapshotCanvas.height = base.height;
        const ctx = snapshotCanvas.getContext('2d');
        if (ctx) ctx.drawImage(base, 0, 0);
    }

    // ---- Overlays (phoneme/word boundaries, highlights, playhead) ----

    /**
     * Draw overlays. Called per-frame from the parent animation loop via
     * bind:this. Writes directly onto the WaveformCanvas's canvas.
     */
    export function drawOverlays(): void {
        if (!waveformRef) return;
        const canvas = waveformRef.getCanvas();
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const width = canvas.width;
        const heightAll = canvas.height;
        const height = heightAll - 30; // leave room for phoneme labels strip
        const lv = get(loadedVerse);
        if (!lv) return;

        const segOffset = lv.tsSegOffset;
        const segEnd = lv.tsSegEnd;
        const duration = segEnd - segOffset || 1;

        // Blit snapshot (pristine waveform) — else redraw from peaks
        if (snapshotCanvas && snapshotCanvas.width) {
            ctx.drawImage(snapshotCanvas, 0, 0);
        } else {
            ctx.fillStyle = '#0f0f23';
            ctx.fillRect(0, 0, width, heightAll);
        }

        const intervals = lv.data.intervals;
        const words = lv.data.words;

        // Phoneme boundaries (thin gray)
        ctx.strokeStyle = '#333';
        ctx.lineWidth = 1;
        for (const iv of intervals) {
            const x = (iv.start / duration) * width;
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, height);
            ctx.stroke();
        }

        // Word boundaries (thicker gold)
        ctx.strokeStyle = '#f0a500';
        ctx.lineWidth = 2;
        for (const w of words) {
            const x = (w.start / duration) * width;
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, height);
            ctx.stroke();
        }

        const audio = get(tsAudioElement);
        if (!audio) return;
        const time = audio.currentTime - segOffset;
        const progress = duration > 0 ? time / duration : 0;

        // Current word highlight (subtle gold)
        for (const w of words) {
            if (time >= w.start && time < w.end) {
                const sx = (w.start / duration) * width;
                const ex = (w.end / duration) * width;
                ctx.fillStyle = 'rgba(240, 165, 0, 0.1)';
                ctx.fillRect(sx, 0, ex - sx, height);
                break;
            }
        }

        // Current phoneme highlight (blue)
        for (const iv of intervals) {
            if (time >= iv.start && time < iv.end) {
                const sx = (iv.start / duration) * width;
                const ex = (iv.end / duration) * width;
                ctx.fillStyle = 'rgba(76, 201, 240, 0.2)';
                ctx.fillRect(sx, 0, ex - sx, height);
                break;
            }
        }

        // Playhead
        const px = progress * width;
        ctx.strokeStyle = PREVIEW_PLAYHEAD_COLOR;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(px, 0);
        ctx.lineTo(px, height);
        ctx.stroke();
        // Triangle marker
        ctx.fillStyle = PREVIEW_PLAYHEAD_COLOR;
        ctx.beginPath();
        ctx.moveTo(px - 6, 0);
        ctx.lineTo(px + 6, 0);
        ctx.lineTo(px, 10);
        ctx.closePath();
        ctx.fill();
    }

    // ---- Click to seek ----

    function onCanvasClick(e: MouseEvent): void {
        if (!waveformRef) return;
        const canvas = waveformRef.getCanvas();
        if (!canvas) return;
        const audio = get(tsAudioElement);
        if (!audio || !audio.duration) return;
        const lv = get(loadedVerse);
        if (!lv) return;

        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const progress = x / canvas.width;
        const duration = lv.tsSegEnd - lv.tsSegOffset;
        const targetRelTime = progress * duration;
        audio.currentTime = targetRelTime + lv.tsSegOffset;
        // Seek + force one overlay redraw (no play).
        drawOverlays();
    }

    // ---- Resize handling ----

    onMount(() => {
        updateSizeFromContainer();
        const onResize = (): void => {
            updateSizeFromContainer();
        };
        window.addEventListener('resize', onResize);
        return () => window.removeEventListener('resize', onResize);
    });

    function updateSizeFromContainer(): void {
        if (!containerEl) return;
        const rect = containerEl.getBoundingClientRect();
        const w = Math.max(1, Math.floor(rect.width));
        if (w !== canvasWidth) {
            canvasWidth = w;
            // Re-slice peaks against new bucket count if we have a verse loaded
            const lv = get(loadedVerse);
            if (lv && pendingUrl) {
                reactToVerse(pendingUrl, lv.tsSegOffset, lv.tsSegEnd);
            }
        }
    }
</script>

<div
    bind:this={containerEl}
    class="visualization"
    on:click={onCanvasClick}
    on:keydown={() => {}}
    role="button"
    tabindex="-1"
>
    <WaveformCanvas bind:this={waveformRef} {peaks} width={canvasWidth} height={canvasHeight} />
    <div class="phoneme-labels" id="phoneme-labels"></div>
</div>
