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
        Most edits fix something. A <strong>flag</strong> does the opposite: it leaves a
        question. Use it for the cases that aren’t a clean fix, like a boundary you’re unsure
        about, a reference that might be wrong, or an audio oddity worth a second pair of eyes.
        Every flag carries a comment explaining what you noticed.
    </p>

    <p>The flag button sits next to <strong>Play</strong> on each segment card:</p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} emphasize={['flag']} />
    </div>

    <p>
        Clicking it opens a small comment box. Write what’s on your mind, then
        <strong>Flag</strong>. The button fills amber so the segment reads as flagged at a glance,
        and the flag appears in the <strong>Flagged Issues</strong> list at the top of this panel.
    </p>

    <p>
        A flag is a short thread. Once it’s set, anyone reviewing this reciter can add a
        <strong>reply</strong> to agree, disagree, or resolve it together. Only the person who
        raised the flag can edit the first comment, and they remove the flag by clearing that
        comment.
    </p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} flagged showFlagComment />
    </div>

    <p class="eg-note">
        Flags don’t block anything; they’re notes, not errors. Leave one whenever you’re unsure
        rather than guessing, and clear it once the question is settled.
    </p>
</div>
