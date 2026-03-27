<h1 align="center">Qur'anic Universal Audio</h1>

<p align="center">
  <a href="https://huggingface.co/spaces/hetchyy/Quran-multi-aligner"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Demo-Qur'an%20Multi--Aligner-yellow" alt="Demo - Qur'an Multi-Aligner"></a>
  <a href="https://huggingface.co/datasets/hetchyy/quranic-universal-ayahs"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Dataset-Qur'anic%20Universal%20Ayahs-blue" alt="Dataset - Qur'anic Universal Ayahs"></a>
  <a href="https://huggingface.co/spaces/hetchyy/Quran-reciter-requests"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Request-Add%20a%20Reciter-ff9d00" alt="Request - Add a Reciter"></a>
  <a href="data/RECITERS.md"><img src="https://img.shields.io/badge/Reciters-380%20Available%20%7C%202%20Aligned-green" alt="Reciters"></a>
  <a href="data/RECITERS.md"><img src="https://img.shields.io/badge/Riwayat-14%20%2F%2020-green" alt="Riwayat"></a>
  <a href="https://github.com/Wider-Community/quranic-universal-audio/releases/latest"><img src="https://img.shields.io/github/v/release/Wider-Community/quranic-universal-audio?label=Release" alt="Latest Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-orange" alt="License"></a>
  <a href="https://github.com/Wider-Community/quranic-universal-audio"><img src="https://img.shields.io/github/stars/Wider-Community/quranic-universal-audio?style=social" alt="GitHub stars"></a>
</p>

<p align="center">The all-in-one audio and timing hub for Qur'anic apps, developers, and researchers. A community-verified dataset featuring 300+ reciters with word- and letter-level timestamps across multiple riwayat.</p>

https://github.com/user-attachments/assets/b81e805b-129e-4be9-af51-94d3babd4bd2

## Key Highlights

- **Unified Qur'anic audio hub** — A single consistent schema with comprehensive metadata for all recitations. No more chasing scattered websites, CDN APIs, YouTube playlists, and raw files with different formats, surah/ayah splits, and inconsistent reciter names.

- **Large-scale, multi-riwayah, multi-style** — Full Qur'an coverage for [300+ reciters and 15+ riwayat](data/RECITERS.md) spanning mujawwad, murattal, muallim, taraweeh and children repeat styles, with dedicated handling of wording and verse numbering differences across riwayat.

- **Phoneme-first alignment** — 20ms phoneme-level precision eliminates ambiguity at word boundaries and resolves tajweed effects like idgham where sounds merge across words. Powered by a state-of-the-art Qur'an-specific ASR model trained on hundreds of hours of diverse recitations, robust across styles, voices, and recording conditions.

- **Repetition-safe, gap-free timestamps** — The pipeline transcribes each silence-based segment independently, so repeated words/verses are detected and timestamped correctly. Word timestamps are padded to fill alignment artefacts, reflecting natural recitation and keeping highlighting perfectly synchronized with no visual gaps. See the [comparison with QUL timestamps](docs/qul_vs_mfa_timestamps.md).

- **Community-driven validation** — No trusting a black-box pipeline. Every stage is automatically checked by dedicated validators and human-correctable through an inspector UI. Review flagged errors like missing words or misaligned boundaries, fix them visually, and the corrections feed back into the dataset.

- **Automated request-to-release pipeline** — [Request or add a reciter](https://huggingface.co/spaces/hetchyy/Quran-reciter-requests) in any supported format and the tooling handles preparation, normalisation, and verification, going from submission to verified release in hours with email updates.

- **Fully reproducible** — Every output records the models, parameters, and settings that produced it, with full traceability backed by Git versioning and documented GitHub Releases.

- **Flexible access** — Consume the data through structured JSON files, Hugging Face dataset, or API-style access, all versioned and auto-updated with each release.

## Data Access

To access the audio or timestamps:

1. **Direct download** — JSON files in [`data/`](data/), or packaged in [GitHub Releases](https://github.com/Wider-Community/quranic-universal-audio/releases)
2. **Hugging Face Dataset** — [quranic-universal-ayahs](https://huggingface.co/datasets/hetchyy/quranic-universal-ayahs)
3. **QUD API** — *(coming soon)*

## Technical Overview

<p align="center">
  <img src="captures/quran_multi_aligner_pipeline.svg" alt="Pipeline diagram">
</p>

The repository uses the following components:

| Component | Description |
|-----------|-------------|
| [`data/`](data/) | Reference data, audio manifests, alignment output, and timestamps, alongside schemas and documentation |
| [`quran_multi_aligner/`](quran_multi_aligner/) | Hugging Face space demonstrating the full pipeline with free GPU processing, also available as an [API](quran_multi_aligner/docs/client_api.md) |
| [`mfa_aligner/`](mfa_aligner/) | MFA forced alignment service for timestamps computation |
| [`inspector/`](inspector/) | Flask web app for browsing, validating, and editing alignment results |
| [`validators/`](validators/) | CLI scripts for validating audio inputs, segments, and timestamps |
| [`reciter_requests`](https://huggingface.co/spaces/hetchyy/Quran-reciter-requests) | Community request form and system for new reciter processing |
| [quranic-phonemizer](https://github.com/Hetchy/Quranic-Phonemizer) | External package — Quran-specific G2P; the foundation that makes phoneme-level alignment possible |


## Contributing

This is a community-based project. While the pipeline is ~95% automated, manual review is essential to guarantee quality. No expertise in tajweed or recitation rules is needed — fixing errors means things like missing words, over/under-segmentation, and low-confidence segments, all done through the inspector UI.

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to get started, or [open an issue](https://github.com/Wider-Community/quranic-universal-audio/issues) for bugs and suggestions.

## License

[Apache 2.0](LICENSE)
