<script lang="ts">
    /**
     * The illustrated body of the "Editing guide" — the one required guide that
     * teaches the editing UI itself rather than a validation category. Mounted
     * by AccordionGuideModal via the `::component{name="editing-guide"}`
     * directive. Pure presentation: every card is an inert `MockSegCard`.
     *
     * Plain language throughout (no jargon); this is required reading, so it
     * leads with a banner saying so.
     */
    import MockSegCard from './MockSegCard.svelte';
    import { synthPeaks } from './synth-peaks';
    import ValActionMock from './ValActionMock.svelte';

    // Deterministic synthetic waveforms; a few seeds for visual variety.
    const wave = synthPeaks(150, 7);
    const waveB = synthPeaks(150, 19);
</script>

<div class="eg-root">
    <div class="eg-banner">📖 Required reading — a quick tour of editing before you start.</div>

    <!-- What is a segment -->
    <p>
        A <strong>segment</strong> is the basic unit the pipeline produces. It listens for
        pauses (where the reciter stops) to cut the recording into pieces, then matches each
        piece to the Quran words it thinks were recited.
    </p>
    <p>Here’s what a single segment card shows:</p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} placeholder />
    </div>

    <!-- Adjust -->
    <h3 class="eg-h">Adjust — fix the start/end times</h3>
    <p>Use <strong>Adjust</strong> when the words are right but the timing is off.</p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} emphasize={['adjust', 'time']} />
    </div>
    <p>Once you enter Adjust, the card switches to trimming:</p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} mode="adjust" />
    </div>
    <p class="eg-note">
        The <span class="eg-ink-start">green</span> line is the start, the
        <span class="eg-ink-end">red</span> line is the end. Move them three ways: drag a line on
        the waveform, tap the <strong>‹ ›</strong> steppers for fine nudges, or type an exact time
        into the time field. Press <strong>Apply</strong> to keep it, <strong>Cancel</strong> to
        drop it. 
    </p>

    <!-- Split -->
    <h3 class="eg-h">Split — cut one segment into two</h3>
    <p>Use <strong>Split</strong> when one segment actually contains two separate parts.</p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} emphasize={['split']} />
    </div>
    <p>Entering Split drops a <span class="eg-ink-split">yellow</span> cursor where the cut will be:</p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} mode="split" compact />
    </div>
    <p class="eg-note">
        Move the cursor (drag, or the <strong>‹ ›</strong> steppers), preview each side with
        <strong>L</strong> / <strong>R</strong>, then press <strong>Split</strong>. When a segment
        crosses a verse boundary or has a repeated phrase, the button reads <strong>Auto Split</strong>
        and pre-places the cuts for you — you confirm and adjust slightly if needed.
    </p>

    <p class="eg-note">
        In Adjust and Split, you can zoom anywhere on the waveform with the mouse wheel for increased precision.
    </p>

    <!-- Edit Ref -->
    <h3 class="eg-h">Edit Ref — change which words it covers</h3>
    <p>
        Use <strong>Edit Ref</strong> when the timing is fine but the matched words are wrong.
        You can click the reference text itself or the <strong>Edit Ref</strong> button.
    </p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} emphasize={['editref', 'ref']} />
    </div>
    <p>The reference turns into a small input you type into:</p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} mode="reference" />
    </div>
    <p class="eg-note">
        References are written <strong>surah:verse:word - surah:verse:word (<code>s:v:w - s:v:w</code>)</strong>. Shortcuts:
        <code>s:v</code> selects the whole verse, <code>s:v:w</code> selects just that one word. Press <strong>Enter</strong> to
        confirm, <strong>Esc</strong> to cancel.

        Entering an empty reference causes it to be a failed alignment with empty text (sometimes useful, see the failed alignments guide).
    </p>

    <!-- Merge -->
    <h3 class="eg-h">Merge ↑ / Merge ↓ — join with a neighbour</h3>
    <p>
        Use a <strong>Merge</strong> when one segment was split too finely. <strong>Merge ↑</strong>
        joins this segment into the one above it; <strong>Merge ↓</strong> joins it into the one below.
        The two become a single segment.
    </p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} emphasize={['merge-prev', 'merge-next']} />
    </div>

    <!-- Delete -->
    <h3 class="eg-h">Delete — remove a segment</h3>
    <p>
        Use <strong>Delete</strong> for a segment that shouldn’t exist — silence, noise, non-Quran speech, weird audio issues. It’s removed from the list (you can always undo it later).
    </p>
    <div class="eg-card-frame">
        <MockSegCard peaks={waveB} emphasize={['delete']} />
    </div>

    <!-- Special ops -->
    <h3 class="eg-h">Two shortcuts on the validation cards</h3>
    <p>
        When the panel flags an issue, some cards offer a one-click fix:
    </p>
    <div class="eg-special">
        <div class="eg-special-col">
            <ValActionMock kind="autofill" />
            <p class="eg-note">
                <strong>Auto-fill</strong> fills in a <em>missing word</em> for you.
            </p>
        </div>
        <div class="eg-special-col">
            <ValActionMock kind="ignore" />
            <p class="eg-note">
                <strong>Ignore</strong> dismisses a flag you’ve checked and decided is fine, for
                that one segment. The warning stops showing for that category.
            </p>
        </div>
    </div>

    <!-- What to edit -->
    <h3 class="eg-h">What to edit</h3>
    <p>
        The bare minimum is fixing all the validation category mistakes (the mark ready form will tell you when those are cleared).
        Since it is not possible to automatically flag every potential error, it is recommended to do some additional checks, such as:
    </p>
    <div style="margin-left: 3em;">
        <ul>
            <li>Listening to entire surahs (using the surah picker) and verifying no issues with segment boundaries and references</li>
            <li>Checking for any audio quality issues</li>
            <li>Increasing the low confidence threshold beyond the default and reviewing those segments as well</li>
            <li>Using filters to search for potentially problematic segments (e.g. 1 or 2 words, many words, very short/long duration segments, etc.)</li>
        </ul>
    </div>

    <!-- Saving & history -->
    <h3 class="eg-h">Saving, and undoing anything</h3>
    <p>
        Your edits are kept as you go. With <strong>auto-save</strong> on they’re saved for you;
        you can also press <strong>Save</strong> yourself at any time. Nothing is ever locked in —
        the <strong>History</strong> panel lists every edit, and you can <strong>undo</strong> any
        of them. You can filter history by the kind of edit or by validation category to find and
        double-check a change.
    </p>

    <p>
        You can always check out a published reciter's history to better understand the edits and types of common issues. It is also recommended to review your edits thoroughly, either from the history after you are done, or by turning autosave off and using manual save occasionally to review the staged changes before confirming the save.
    </p>
</div>
