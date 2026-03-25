# Contributing

Thank you for your interest in contributing to Qur'anic Universal Audio. This is a community project and your help is greatly appreciated.

## Getting started

1. **Fork** the repository on GitHub
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/<your-username>/quranic-universal-audio.git
   cd quranic-universal-audio
   ```
3. Make your changes (see below for what you can contribute)
4. **Commit** the updated JSON files:
   ```bash
   git add data/recitation_segments/<reciter>/segments.json data/recitation_segments/<reciter>/detailed.json
   git commit -m "fix: correct segmentation errors for <reciter>"
   ```
5. **Push** and open a pull request:
   ```bash
   git push origin main
   ```
   Then open a PR against `main` on the [upstream repository](https://github.com/Wider-Community/quranic-universal-audio/pulls).

## Ways to contribute

### Add a new reciter or request alignment

- **Add audio yourself** — Create an audio manifest and submit a PR. See [Adding a New Reciter](data/README.md#adding-a-new-reciter) for the expected format and steps.
- **Request processing** — Use the [reciter request form](https://huggingface.co/spaces/hetchyy/Quran-reciter-requests) to request segmentation and timestamping for a specific reciter.

### Review and fix segments

The most impactful contribution is reviewing alignment results and fixing errors using the [inspector](inspector/). No expertise in tajweed or recitation rules is required — the inspector's validation panel flags issues automatically:

- **Missing verses** — verses with no segments at all
- **Missing words** — words not covered by any segment in a verse
- **Failed alignments** — segments where the aligner couldn't find a match
- **Low confidence** — segments where the alignment score is below threshold
- **Over-segmentation** — a word's recitation accidentally split across two segments
- **Under-segmentation** — multiple pause groups merged into one segment
- **Cross-verse segments** — segments spanning multiple verses that may need splitting
- **Audio bleeding** — a verse's audio file containing audio from an adjacent verse

**Workflow:**

1. Set up and run the inspector — see the [inspector README](inspector/README.md) for setup instructions and video guides on editing segments
2. Select a reciter and review the validation panel for flagged issues
3. Fix errors using the editing tools (adjust boundaries, split, merge, re-reference)
4. Validation re-runs automatically after each save — keep going until all errors and warnings are resolved
5. Submit a PR with the updated JSON files

### Report issues

[Open an issue](https://github.com/Wider-Community/quranic-universal-audio/issues) for bugs, incorrect timestamps, feature requests or optimisations.

## Technical contributions

The ASR and forced alignment models are not currently public, so technical contributions to the core pipeline are limited. If you have ideas for technical collaboration, feel free to reach out!
