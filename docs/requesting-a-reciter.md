# Requesting a Reciter

This guide walks you through the process of requesting segmentation for a new Quran reciter — from choosing the right parameters to reviewing the final output.

## Overview

The pipeline takes full-surah or per-ayah audio recordings and produces word-level time segments for every verse. The key parameter you control is **min silence** — the minimum duration of silence (in milliseconds) that triggers a segment split. Getting this right avoids over-segmentation (too many tiny segments splitting words) or under-segmentation (multiple pause groups merged together).

## Step 1: Find a good min silence value

Before submitting a request, spend a few minutes testing the parameter on the [Quran Multi-Aligner](https://huggingface.co/spaces/hetchyy/Quran-multi-aligner) to find a value that works well for your reciter.

### Download a test chapter

1. Open the **Inspector** and go to the **Audio** tab
2. Select your reciter and pick one or two medium-length chapters (e.g. chapters 18, 36, or 67)
3. Download the audio file from the audio player widget

### Test on the Multi-Aligner

1. Go to the [Quran Multi-Aligner Space](https://huggingface.co/spaces/hetchyy/Quran-multi-aligner)
2. Upload the downloaded audio
3. Click Extract Segments to run alignment
4. Look at the results:
   - **Number of segments found** — is it reasonable for the chapter length?
   - **Listen to a few clips** — does each segment contain a clean phrase or verse fragment?
   - **Check for problems:**
     - Over-segmentation: a single word or partial word in its own segment (silence value too low)
     - Under-segmentation: long segments containing multiple distinct pause groups (silence value too high)
5. Click **Resegment with new settings** to try different min silence values without re-uploading:
   - Try values higher and lower than the initial
   - Compare the segment counts and spot-check a few clips each time
   - Narrow in on a range that gives clean, natural splits

### General guidelines

| Recitation style | Typical min silence |
|------------------|--------------------|
| **Murattal**     | 200–500ms          |
| **Mujawwad**     | 600–1200ms         |

These are starting points — every reciter is different. The test above will tell you what actually works.

## Step 2: Submit your request

Once you've found a good min silence value, submit your request using either method:

- **From the Inspector:** Go to the **Requests** tab, fill in the form, and click Submit
- **From the HF Space:** Visit the [Reciter Requests Space](https://huggingface.co/spaces/hetchyy/Quran-reciter-requests) and fill in the form

### Form fields

- **Request Type** — select "New reciter" for first-time processing, or "Re-align" to re-run with different parameters (see below)
- **Reciter** — pick from the dropdown of available reciters. If your reciter is not listed, you'll need to add the audio manifest first (see note below) and wait for the PR to be merged before it appears
- **Riwayah** — the Quranic reading tradition. Most existing reciters default to Hafs an Asim in their metadata, and this is true for the vast majority. However, it should be verified when submitting a request — listen to the recitation and allocate the correct riwayah
- **Min Silence** — your suggested value from Step 1

Both methods create a public [GitHub Issue](https://github.com/Wider-Community/quranic-universal-audio/issues?q=label%3Arequest) to track progress. You'll receive a link to the issue after submission.

You will be notified by email when the request is approved and the segments have been extracted.

### Adding a new reciter

If the reciter you want is not in the dropdown, their audio manifest hasn't been added to the repository yet. To add one:

1. Create the audio manifest JSON following the [Adding a New Reciter](../data/README.md#adding-a-new-reciter) guide
2. Submit a PR with the manifest file
3. Wait for the PR to be merged — the reciter will then appear automatically in the request form dropdowns

## Step 3: Review segments in the Inspector

Once the segments are extracted, you'll receive an email notification. The segments will be available in the Inspector for review.

1. Pull the latest changes from the repository
2. Run the inspector and edit segments. See the [inspector README](../inspector/README.md) for setup instructions, video guides, and detailed documentation on the editing tools.

### Optional: Re-align with different parameters

After reviewing the segments in the Inspector, you may find that the number of issues is very high — for example, widespread over-segmentation or under-segmentation across many chapters. In this case, it may be more efficient to re-run the pipeline with a different min silence value rather than manually fixing hundreds of segments.

To do this, submit a new request for the same reciter using **"Re-align"** as the request type, with an adjusted min silence value. The previous segments will be replaced with the new run.

## Step 4: Submit a pull request

Once you've reviewed and fixed the segments:

1. Commit the updated segment files:
   ```bash
   git add data/recitation_segments/<reciter>/segments.json data/recitation_segments/<reciter>/detailed.json
   git commit -m "fix: correct segmentation errors for <reciter>"
   ```
2. Push and open a pull request against `main`
3. The PR will be reviewed and merged
4. After merging, the timestamp extraction pipeline will run automatically
5. You will be notified by email once the timestamps are complete and the data is published
