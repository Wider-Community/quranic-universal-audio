# Requesting a Reciter

This guide walks you through the process of requesting alignment and timestamps generation for a new Qur'an reciter.

## Overview

The pipeline takes full-surah or per-ayah audio recordings and produces pause segments for every verse. The key parameter you control is **min silence** — the minimum duration of silence (in milliseconds) that triggers a segment split. Getting this right avoids over-segmentation (too many short segments, even when a reciter does wasl) or under-segmentation (multiple cross-verses or pause groups merged together, even when the reciter does waqf).

## Step 1: Find a good min silence value

### Test on the Aligner

1. Download reciter audio:
    - Open the **Inspector**, go to the **Audio** tab, select your reciter and pick one or two medium-length chapters (e.g. chapters 18, 36, or 67) to download from the audio player widget
    - Alternatively, download directly from the original source in `data/audio/.../<reciter>.json`.
2. Go to the [Quranic Universal Aligner Space](https://huggingface.co/spaces/hetchyy/quranic-universal-aligner) and upload the audio
3. Click Extract Segments to run alignment and observe the results:
   - **Number of segments found** — is it reasonable for the chapter length?
   - **Listen to a few clips** — does each segment contain a clean phrase or verse fragment?
   - **Check for problems:**
     - Over-segmentation: a single word or partial word in its own segment (silence value too low)
     - Under-segmentation: long segments containing multiple distinct pause groups (silence value too high)
4. Click **Resegment with new settings** to try different min silence values without re-uploading:
   - Try values higher and lower than the initial
   - Compare the segment counts and spot-check a few clips each time
   - Narrow in on a range that gives clean, natural splits, consistent for different chapters

You can also see the thresholds used for already processed reciters in the reciter form as a general guide.

## Step 2: Submit your request

Once you've found a good min silence value, submit your request using the [Reciter Requests Form](https://huggingface.co/spaces/hetchyy/Quran-reciter-requests). You should verify the loaded metadata and riwayah for the reciter to ensure accurate processing.

Once done, you will receive a confirmation email, and a [GitHub Issue](https://github.com/Wider-Community/quranic-universal-audio/issues) will be created to track progress. 


## (Optional) Step 3: Review segments in the Inspector

If you opted to review the results yourself, see the [Contribution Guide](CONTRIBUTING.md) and the [Inspector README](inspector/README.md) for further details. Otherwise, one of our active contributors will eventually pick up the issue and handle the reviewing.

In either case, you will receive an email when alignment is done and timestamps are ready.