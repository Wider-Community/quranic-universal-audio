<h1 align="center">Qur'anic Universal Audio</h1>

<p align="center">
  <a href="https://huggingface.co/spaces/hetchyy/Quran-multi-aligner"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Demo-Qur'an%20Multi--Aligner-yellow" alt="Demo - Qur'an Multi-Aligner"></a>
  <a href="https://huggingface.co/datasets/hetchyy/quranic-universal-ayahs"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Dataset-Qur'anic%20Universal%20Ayahs-blue" alt="Dataset - Qur'anic Universal Ayahs"></a>
  <a href="https://github.com/Wider-Community/quranic-universal-audio/releases/latest"><img src="https://img.shields.io/github/v/release/Wider-Community/quranic-universal-audio?label=Release" alt="Latest Release"></a>
  <a href="data/RECITERS.md"><img src="https://img.shields.io/badge/Reciters-211%20Available%20%7C%203%20Aligned-green" alt="Reciters"></a>
  <a href="https://www.python.org"><img src="https://img.shields.io/badge/Python-3.10+-3776ab" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-orange" alt="License"></a>
  <a href="https://github.com/Wider-Community/quranic-universal-audio"><img src="https://img.shields.io/github/stars/Wider-Community/quranic-universal-audio?style=social" alt="GitHub stars"></a>
</p>

<p align="center">A large-scale database of Qur'an recitation audio with precise word- and letter-level timestamps. Audio is processed from full surah or verse recordings into pause-based segments, then force-aligned against the detected Qur'anic text.</p>

<p align="center">
  <img src="captures/quran_multi_aligner_pipeline.svg" alt="Pipeline diagram">
</p>

https://github.com/user-attachments/assets/d6bffa29-5e71-492b-b0ec-b6a34c19a693

## Use cases

- **Word-highlighted recitation** — Accurate word and letter timestamps for highlighting in Qur'an apps, learning tools, and educational platforms.
- **Generate EveryAyah style audio from surah recordings** — Extract per-ayah audio clips from full-surah recordings, producing verse-by-verse files for any reciter even when only surah-level audio exists.
- **Tajweed timing analysis** — Subword-level timestamps let you measure durations of tajweed rules (e.g. madd and ghunnah lengths) across expert reciters.
- **Unified multi-reciter audio access** — Browse and access audio from hundreds of reciters across multiple sources through a single unified format with consistent JSON schemas.

## Components

| Component | Description |
|-----------|-------------|
| [`data/`](data/) | Reference data, audio manifests, alignment output, and timestamps, alongside schemas and documentation |
| [`quran_multi_aligner/`](quran_multi_aligner/) | Hugging Face space demonstrating the full pipeline with free GPU processing, also available as an [API](quran_multi_aligner/docs/client_api.md) |
| [`mfa_aligner/`](mfa_aligner/) | MFA forced alignment service for timestamps computation |
| [`inspector/`](inspector/) | Flask web app for browsing, validating, and editing alignment results |
| [`validators/`](validators/) | CLI scripts for validating audio inputs, segments, and timestamps |
| [`reciter_requests`](https://huggingface.co/spaces/hetchyy/Quran-reciter-requests) | Community request form and system for new reciter processing |
| [quranic-phonemizer](https://github.com/Hetchy/Quranic-Phonemizer) | External package — Quran-specific G2P; the foundation that makes phoneme-level alignment possible |

## Key Highlights & features

- **Phoneme-level alignment.** Most Qur'an audio tools align at the word level. This project aligns at the phoneme level first, then recovers word and letter boundaries from the phoneme timestamps. The result is significantly more precise and accurate word timings.

- **Gap-free timestamps.** Within each recitation segment, word timestamps are padded forward so there are no artificial gaps between words. Highlighting stays perfectly synchronized with the audio — no silent flickers between words that other tools produce.

- **Handles cross-word tajweed  naturally.** Rules like idgham, where sounds span word boundaries are resolved at the phoneme level. There is no ambiguity about where one word ends and the next begins.

- **Handles repetitions naturally.** Because the pipeline first segments by silences and then transcribes each segment independently, repeated words or verses are detected and timestamped correctly — each occurrence gets its own timestamps.

- **Robust validation and inspection.** Three dedicated validators check every stage of the pipeline, and the inspector provides a full editing UI with waveform visualization, confidence scoring, and playback for verifying segments and timestamps quality and editing them.

- **Community-reviewed.** Unlike static dataset releases, this project is open for anyone to inspect, fix, and improve the data through the inspector and pull requests. Quality improves continuously as more people review and correct errors.

- **Full provenance and reproducibility.** Every output file records the models, parameters, and sources used to produce it via `_meta` blocks across all three pipeline stages — audio manifests (reciter, riwayah, source, audio category), segments (models, thresholds), and timestamps (alignment settings). Results are fully traceable and reproducible. Git versioning and Github Releases track all changes to the data over time.

See the [detailed comparison with QUL timestamps](docs/qul_vs_mfa_timestamps.md) for concrete examples of accuracy and robustness to repetitions.

## Accessing the data

If you're just here for the audio, timestamps or segment data, you can access them as follows:

1. **Direct download** — JSON files in [`data/`](data/), or packaged in [GitHub Releases](https://github.com/Wider-Community/quranic-universal-audio/releases)
2. **Hugging Face Dataset** — [quranic-universal-ayahs](https://huggingface.co/datasets/hetchyy/quranic-universal-ayahs)
3. **QUD API** — *(coming soon)*

## Contributing

This is a community project. The pipeline is automated, but manual review is essential to guarantee quality. No expertise in tajweed or recitation rules is needed — fixing errors means things like missing words, over/under-segmentation, and low-confidence segments, all done through the inspector UI.

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to get started, or [open an issue](https://github.com/Wider-Community/quranic-universal-audio/issues) for bugs and feature requests.

## License

[Apache 2.0](LICENSE)
