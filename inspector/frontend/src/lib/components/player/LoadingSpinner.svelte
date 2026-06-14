<script lang="ts">
    /**
     * LoadingSpinner — the shared audio-loading indicator.
     *
     * A ring with a brighter top arc rotating 0.7s linear (1.4s under
     * `prefers-reduced-motion`). Promoted out of the Segments footer play
     * button (issue #172) so every tab's transport can show the SAME honest
     * "audio is loading" affordance during the click/seek → first-audible gap.
     *
     * Contract: this is purely presentational — it has no knowledge of any
     * port or store. Mount it whenever the owning player's buffering state is
     * true; that state must be raised on play/seek/source-change intent (or
     * the port's `waiting` event) and cleared on the port's `playing` event
     * (first audible frame), NOT on `play`/`canplay`. See each tab's player.
     *
     * Used by: SegmentsFooter (accent play button), PlayerControls
     * (Dashboard + Timestamps shared transport).
     *
     * @prop size  — ring diameter in px (default 16).
     * @prop color — arc color (default `currentColor` so the host button's
     *               text/accent-fg color themes it; pass an explicit
     *               `var(--accent-fg)` etc. when the host color differs).
     */
    interface Props {
        size?: number;
        color?: string;
    }

    const { size = 16, color = 'currentColor' }: Props = $props();
</script>

<span
    class="loading-spinner"
    style:--spinner-size="{size}px"
    style:--spinner-color={color}
    aria-hidden="true"
></span>

<style>
    .loading-spinner {
        display: inline-block;
        /* Never let a flex/grid parent (e.g. the Dashboard/Timestamps flex
         * transport row) shrink the ring below its size — without this the
         * width collapses to min-content (~border only) and it renders as a
         * thin sliver instead of a circle. min-width pins it in any context. */
        flex: 0 0 auto;
        box-sizing: border-box;
        width: var(--spinner-size);
        height: var(--spinner-size);
        min-width: var(--spinner-size);
        min-height: var(--spinner-size);
        border-radius: 50%;
        border: 2px solid oklch(from var(--spinner-color) l c h / 0.35);
        border-top-color: var(--spinner-color);
        animation: loading-spin 0.7s linear infinite;
    }
    @media (prefers-reduced-motion: reduce) {
        .loading-spinner {
            animation-duration: 1.4s;
        }
    }
    @keyframes loading-spin {
        to {
            transform: rotate(360deg);
        }
    }
</style>
