# Inspector

Flask web app for reviewing and editing Quran recitation alignment results. Four tabs: **Timestamps** (waveform + karaoke phoneme display), **Segments** (browse/edit alignment output with validation), **Audio** (hierarchical recording browser), **Requests** (submit and track reciter requests).

## Setup

```bash
pip install -r inspector/requirements.txt
```

## Run

```bash
python inspector/server.py
```

Open http://localhost:5000.

## Segments Tab — Validation Categories

The error categories are:

| Category | Description |
|----------|-------------|
| **Failed Alignments** | Segment has no matched reference (alignment completely failed) |
| **Missing Verses** | Expected verse has zero segment coverage |
| **Missing Words** | Gap in word indices within a covered verse |
| **Structural Errors** | Invalid time/word ordering: inverted times, out-of-bounds word indices, or time overlap between consecutive segments |
| **Low Confidence** | Alignment confidence below 80% |
| **Oversegmented** | Potential accidental cuts from the segmenter |
| **Cross-verse** | Segment spans multiple verses |
| **Audio Bleeding** | Segment matched to a different verse than its source audio file (by_ayah only) |

### Error Overlap

**Failed** and **Missing Verses** can co-occur: if all segments for a verse failed alignment, that verse also shows as missing. Neither overlaps with other categories.

Remaining categories that can co-occur on the same segment:

| | Missing Words | Structural | Low Confidence | Oversegmented | Cross-verse | Audio Bleeding |
|---|---|---|---|---|---|---|
| **Missing Words** | — | Yes | Yes | Yes | Yes | Yes |
| **Structural** | | — | Yes | Yes | Yes | No |
| **Low Confidence** | | | — | Yes | Yes | Yes |
| **Oversegmented** | | | | — | No | Yes |
| **Cross-verse** | | | | | — | Yes |

## Segments Tab — Editing Operations

| Operation         | Description |
|-------------------|-------------|
| **Adjust**        | Drag handles or enter timestamps to modify start/end time |
| **Split**         | Divide audio segment into two |
| **Merge**         | Combine two adjacent segments audio and text |
| **Edit Reference**| Inline edit of Qur'anic text |
| **Delete**        | Remove segment entirely |
| **Auto-fix** [Missing Word errors] |  Intelligently extend segment to cover a missing word |
| **Ignore** [Low Confidence, Oversegmented, Cross-Verse errors] |  Dismiss issue, set confidence to 1 |
