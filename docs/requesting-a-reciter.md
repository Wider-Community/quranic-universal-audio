# Requesting a Reciter

This guide walks you through the process of requesting segmentation for a new Quran reciter — from choosing the right parameters to reviewing the final output.

## Overview

The pipeline takes full-surah or per-ayah audio recordings and produces word-level time segments for every verse. The key parameter you control is **min silence** — the minimum duration of silence (in milliseconds) that triggers a segment split. Getting this right avoids over-segmentation (too many tiny segments splitting words) or under-segmentation (multiple pause groups merged together).

## Step 1: Find a good min silence value

Before submitting a request, spend a few minutes testing the parameter on the [Quranic Universal Aligner](https://huggingface.co/spaces/hetchyy/quranic-universal-aligner) to find a value that works well for your reciter.

### Download a test chapter

1. Open the **Inspector** and go to the **Audio** tab
2. Select your reciter and pick one or two medium-length chapters (e.g. chapters 18, 36, or 67)
3. Download the audio file from the audio player widget

### Test on the Aligner

1. Go to the [Quranic Universal Aligner Space](https://huggingface.co/spaces/hetchyy/quranic-universal-aligner)
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

- **Reciter** — pick from the dropdown of available reciters. If your reciter is not listed, you'll need to add the audio manifest first (see note below) and wait for the PR to be merged before it appears
- **Riwayah** — the Quranic reading tradition. Most existing reciters default to Hafs an Asim in their metadata, and this is true for the vast majority. However, it should be verified when submitting a request — listen to the recitation and allocate the correct riwayah
- **Min Silence** — your suggested value from Step 1

Both methods create a public [GitHub Issue](https://github.com/Wider-Community/quranic-universal-audio/issues?q=label%3Arequest) to track progress. You'll receive a link to the issue after submission.

You will be notified by email when the request is approved and the segments have been extracted.

### Adding a new reciter

If the reciter you want is not in the dropdown, their audio manifest hasn't been added to the repository yet. To add one:

1. Create the audio manifest JSON following the [Adding a New Reciter](adding-a-reciter.md) guide
2. Submit a PR with the manifest file
3. Wait for the PR to be merged — the reciter will then appear automatically in the request form dropdowns

## Step 3: Review segments in the Inspector

Once the segments are extracted, you'll receive an email notification with a link to a **draft pull request**. Each reciter gets its own PR so you can review and fix independently. The PR stays in draft while you're editing — mark it ready when you're done.

### Claim the PR

Assign yourself to the PR so others know you're working on it and avoid duplicate edits:

```bash
gh pr edit <PR_NUMBER> --add-assignee @me
```

Or click **"assign yourself"** on the PR page in GitHub.

### Checkout the PR branch

```bash
# Fetch and checkout the PR branch (easiest method)
gh pr checkout <PR_NUMBER>

# Or manually:
git fetch origin feat/add-segments-<reciter_slug>
git checkout feat/add-segments-<reciter_slug>
```

### Run the Inspector

```bash
python inspector/server.py
```

Open http://localhost:5000, go to the **Segments** tab, select the reciter, and work through the validation issues. See the [inspector README](../inspector/README.md) for setup instructions, video guides, and detailed documentation on the editing tools.

### Push fixes to the PR

All your corrections go directly on the PR branch — no need to open a separate PR:

```bash
git add data/recitation_segments/<reciter>/*
git commit -m "fix: correct segmentation errors for <reciter>"
git push
```

You can push multiple rounds of fixes. The PR stays open until you're satisfied with the quality.

## Step 4: Mark ready and merge

Once you're satisfied with the segment quality:

1. Mark the draft PR as ready for review — either click **"Ready for review"** on the PR page in GitHub, or run:
   ```bash
   gh pr ready
   ```
2. The PR will be reviewed and merged
3. After merging, the timestamp extraction pipeline will run automatically
4. You will be notified by email once the timestamps are complete and the data is published
