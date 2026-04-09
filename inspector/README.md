# Inspector

Flask web app for reviewing and editing Quran recitation alignment results. Three tabs: **Timestamps**, **Segments**, and **Audio**.

## Setup

```bash
pip install -r inspector/requirements.txt
```

## Run

```bash
python inspector/server.py
```

Open http://localhost:5000.


## Segments Reviewing

The main editing interface in the **Segments** tab. Browse the AI-generated segments, review flagged errors, and fix them so timestamps can be generated.

> **Important**: Make sure to save edits regularly to avoid losing work. The app does not auto-save, and unsaved changes might be lost if you refresh or navigate away.

### Getting started

Click **Download All Audio** to cache all chapter audio locally (~1-2 GB). This makes playback instant while editing. If you prefer not to, audio loads lazily with a few seconds delay per new chapter.

While audio downloads, browse another reciter's **edit history** to see what typical fixes look like — this is a good first-time orientation. You can also open the **statistics** panel for graphs on confidence scores, segment durations, words per segment, and other distribution metrics.

<!-- screenshot: download button + statistics panel -->


### Editing operations

| Operation | Description |
|-----------|-------------|
| **Adjust** | Drag handles on the waveform to modify the segment's start and end time |
| **Split** | Divide a segment into two at the playhead position |
| **Merge** | Combine two adjacent segments into one |
| **Edit Reference** | Change the matched Qur'anic text reference |
| **Delete** | Remove a segment entirely |
| **Auto-fix** | Extend an adjacent segment to cover a missing word (available on Missing Words cards) |
| **Ignore** | Dismiss the issue for this category, marking the segment as reviewed-and-correct |


### Error categories

Segments are validated automatically and upon every save. Issues appear in collapsible accordions grouped by category. The table below summarises each category, its priority, and the typical fix.

| Category | Priority | Typical fix |
|----------|----------|-------------|
| Failed Alignments | Must fix | Delete, merge, or edit reference |
| Missing Verses | Must fix | Check failed alignments first |
| Missing Words | Must fix | Auto-fix or edit reference |
| Detected Repetitions | Should fix | Ignore or split |
| Low Confidence | Should fix | Ignore, merge, or adjust |
| Cross-verse | Highly recommended | Ignore or split at pause |
| Qalqala | Highly recommended | Ignore or adjust boundary |
| Muqattaat | Display only | Edit if needed |

> **General tip:** if a flagged segment has no actual error, click **Ignore** to so it disappears from the category and help us know that it is reviewed and correct.

---

#### Failed Alignments

The segment has no matched Qur'anic reference — alignment completely failed. This could mean the segment should be **deleted** (noise or silence), **merged** with the previous or next segment (the split was wrong), or it could be a valid segment that just wasn't detected — in that case, **edit the reference** to assign the correct text.

<!-- screenshot: failed alignment example with action buttons -->

#### Missing Verses

A verse has zero segment coverage. Either the verse is genuinely missing from the audio, or all segments covering that verse failed alignment. Check the **Failed Alignments** category first — fixing those often resolves missing verses automatically.

<!-- screenshot: missing verse card -->

#### Missing Words

A gap in word indices between two segments within a verse. Most of the time, **auto-fix** handles this — it intelligently detects which adjacent segment the word belongs to and extends it. When using auto-fix, verify that the audio actually contains the word and it wasn't cut off at the boundary. If auto-fix is not available, **edit reference** directly on the relevant segment.

<!-- screenshot: missing words with auto-fix button -->

#### Detected Repetitions

The reciter repeated the same text (or part of it) detected in that segment. These can be false detections. **Ignore** if the detection is wrong, or **split** the segment based on how it was actually recited, including repetitions. In general, if there is a few hundred flagges segments as cross-verse, a portion of them are likely segmentation failures of undetcted pauses. 

<!-- screenshot: repetition card -->

#### Low Confidence

Alignment confidence is below the threshold. This could be a genuine mismatch, model noise, or simply uncertainty on a segment that is fully correct. The fix varies: **ignore** if the segment sounds fine, **merge** if it was over-split, **adjust boundaries** if the timing is slightly off, or **edit reference** if the text is wrong.

<!-- screenshot: low confidence card with slider -->

#### Cross-verse

A segment spans multiple verses. If the reciter recited them continuously without pausing, **ignore** — the segment is correct as-is. If the reciter did pause between verses, **split** the segment at the pause point. This is highly recommended because verse-level timestamps and audio clips rely on accurate verse boundaries.

<!-- screenshot: cross-verse segment -->

#### Qalqala

The last word of the segment ends with a qalqala letter (ق ط ب ج د). Check the end of the segment audio to verify the qalqala sound is audible. Most of the time this is either **ignored** (sound is present) or **adjusted** so the boundary captures the full sound.

This is especially important at verse boundaries — the HuggingFace dataset reconstructs audio clips for every verse, so a missing qalqala means the listener hears a cut-off ending. If the segment is mid-verse, it's less critical but still good to fix. The letter ق tends to have the most issues, but this varies by reciter and the silence thresholds used during segmentation.

<!-- screenshot: qalqala segment with waveform showing the sound -->

#### Muqattaat

Segments starting with huruf muqattaat (e.g. الم, طه, يس). Flagged for manual checking only — no ignore needed. Edit if there are any issues with the reference or boundaries.

<!-- screenshot: muqattaat segment -->

<!-- screenshot: editing operations in action -->

### Further quality checks

The automatic error categories are best-effort and catch most issues, but some errors can go undetected. A few additional things you can do:

1. **Listen through full chapters** — load a chapter in the main display and play through all its segments (use auto-play for convenience, or single-segment play for accurate checking of each segment's audio cutoff boundaries). This catches errors that automated checks miss.
2. **Use the filters** — combine filters on duration, word count, verses spanned, confidence, and silence between segments to surface unusual combinations that might indicate problems.
3. **Raise the confidence threshold** — the default low-confidence cutoff is 80%. Increasing it to 85 or 90 surfaces more segments for review. Lower confidence doesn't always mean an error (it can be model noise or uncertainty), but checking these gives greater certainty that the data is correct.

### Edit history

Every save is recorded in the edit history. You can browse past edits, filter by edit type or error category, and sort. You can use the **Undo** button to reverse any edit. 

### Continuous improvement

The first round of review (before the pull request is merged) focuses on fixing the critical issues. But improvement is ongoing — you can come back at any point to do further checks or optional edits. New edits automatically recompute timestamps and sync to the dataset.

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| Space | Play / Pause |
| ← / → | Seek backward / forward 3 seconds |
| ↑ / ↓ | Previous / next segment |
| , / . | Slower / faster playback speed |
| J | Scroll current segment into view |
| E | Edit reference of current segment |
| S | Save changes |
| Enter | Confirm trim or split |
| Escape | Cancel edit |

## Suggestions and feedback

We're continuously improving the Inspector to make reviewing as smooth as possible. If you have ideas, we'd love to hear them — [open an issue](https://github.com/Wider-Community/quranic-universal-audio/issues) about any of the following:

- Feedback on the current error categories, their accuracy in flagging segments, and how well they help you find real issues
- Suggestions for new error categories or detection improvements
- Ideas for new fix types or ways to reduce common errors in the pipeline
- Ways to improve the reviewer experience, make it more enjoyable, and reduce the time it takes to review a reciter
- General UI improvements, new features, or bug reports
- General improvements for the timestamps and audio tabs experience
