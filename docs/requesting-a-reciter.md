# Requesting a Reciter

This guide walks you through the process of requesting segmentation for a new Quran reciter — from choosing the right parameters to reviewing the final output.

## Overview

The pipeline takes full-surah or per-ayah audio recordings and produces word-level time segments for every verse. The key parameter you control is **min silence** — the minimum duration of silence (in milliseconds) that triggers a segment split. Getting this right avoids over-segmentation (too many tiny segments) or under-segmentation (multiple pause groups merged together).

## Step 1: Find a good min silence value

Before submitting a request, spend a few minutes testing the parameter on the [Quran Multi-Aligner](https://huggingface.co/spaces/hetchyy/Quran-multi-aligner) to find a value that works well for your reciter.

### Download a test chapter

1. Open the **Inspector** and go to the **Audio** tab
2. Select your reciter and pick one or two medium-length chapters (e.g. chapters 18, 36, or 67 — long enough to have variety but not so long that testing is slow)
3. Right-click the audio player and save/download the audio file

### Test on the Multi-Aligner

1. Go to the [Quran Multi-Aligner Space](https://huggingface.co/spaces/hetchyy/Quran-multi-aligner)
2. Upload the downloaded audio and select the corresponding chapter
3. Run alignment with the default settings
4. Look at the results:
   - **Number of segments found** — is it reasonable for the chapter length?
   - **Listen to a few clips** — does each segment contain a clean phrase or verse fragment?
   - **Check for problems:**
     - Over-segmentation: a single word or partial word in its own segment (silence value too low)
     - Under-segmentation: long segments containing multiple distinct pause groups (silence value too high)
5. Click **Resegment with new settings** to try different min silence values without re-uploading:
   - Try a value ~200ms higher and ~200ms lower than the default
   - Compare the segment counts and spot-check a few clips each time
   - Narrow in on a range that gives clean, natural splits

### General guidelines

| Recitation style | Typical min silence | Why |
|-----------------|-------------------|-----|
| **Murattal** (teaching/study pace) | 200–500ms | Shorter pauses between phrases |
| **Mujawwad** (melodic/performance) | 600–1200ms | Longer melodic holds and pauses |

These are starting points — every reciter is different. The test above will tell you what actually works.

## Step 2: Submit your request

Once you've found a good min silence value, submit your request using either method:

- **From the Inspector:** Go to the **Requests** tab, select the reciter, enter your suggested min silence, your name and email, and click Submit
- **From the HF Space:** Visit the [Reciter Requests Space](https://huggingface.co/spaces/hetchyy/Quran-reciter-requests) and fill in the form

Both methods create a public [GitHub Issue](https://github.com/Wider-Community/quranic-universal-audio/issues?q=label%3Arequest) to track progress. You'll receive a link to the issue after submission.

You will be notified by email when the request is approved and the segments have been extracted.

## Step 3: Review segments in the Inspector

Once the segments are extracted, you'll receive an email notification. The segments will be available in the Inspector for review.

1. Pull the latest changes from the repository
2. Run the Inspector (`python inspector/server.py`)
3. Go to the **Segments** tab and select your reciter
4. Work through the **validation panel** — it flags issues automatically:
   - Missing verses or words
   - Failed or low-confidence alignments
   - Cross-verse segments that may need splitting
   - Over/under-segmentation
5. Fix errors using the editing tools (adjust boundaries, split, merge, re-reference)
6. Validation re-runs automatically after each save — keep going until all errors are resolved

See the [inspector README](../inspector/README.md) for setup instructions, video guides, and detailed documentation on the editing tools.

### Optional: Re-request with different parameters

After reviewing the segments in the Inspector, you may find that the number of issues is very high — for example, widespread over-segmentation or under-segmentation across many chapters. In this case, it may be more efficient to re-run the pipeline with a different min silence value rather than manually fixing hundreds of segments.

To do this, submit a **new request** for the same reciter with an adjusted min silence value. In the notes field, mention that this is a re-run and reference the original issue. The previous segments will be replaced with the new run.

## Step 4: Submit a pull request

Once you've reviewed and fixed the segments:

1. Commit the updated segment files:
   ```bash
   git add data/recitation_segments/<reciter>/segments.json data/recitation_segments/<reciter>/detailed.json
   git commit -m "fix: correct segmentation errors for <reciter>"
   ```
2. Push and open a pull request against `main`
3. The PR will be reviewed and merged
4. After merging, the timestamp extraction pipeline (MFA forced alignment) will run automatically to generate word-level, letter-level, and phoneme-level timestamps
5. You will be notified by email once the timestamps are complete and the data is published
