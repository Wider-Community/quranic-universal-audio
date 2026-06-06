<script lang="ts">
    /**
     * The illustrated body of the "Flagging" guide. Mounted by
     * AccordionGuideModal via the `::component{name="flagging-demo"}` directive.
     *
     * Pure presentation: a mock `MockSegCard` with the flag button spotlit,
     * then a second mock showing a flagged segment with its comment thread.
     * Reuses the global `.eg-*` guide chrome and the synthetic waveform — no
     * live audio or dispatch.
     */
    import MockSegCard from './MockSegCard.svelte';
    import { synthPeaks } from './synth-peaks';

    const wave = synthPeaks(150, 11);
</script>

<div class="eg-root">
    <p>
        Most edits fix something. A <strong>flag</strong> only leaves a
        question/comment. Use it for the cases that aren’t a clean fix, an audio outlier, or a reciter mistake. Add a comment alongside the flag.
    </p>

    <div class="eg-card-frame">
        <MockSegCard peaks={wave} emphasize={['flag']} />
    </div>

    <p>
        Once a flag is set, anyone can reply to help resolve the issue.
    </p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} flagged showFlagComment />
    </div>
</div>
