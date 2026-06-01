<h1 align="center">Qur'anic Universal Audio</h1>

<p align="center">
  <a href="https://huggingface.co/spaces/hetchyy/quranic-universal-aligner"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Tool-Qur'anic%20Universal%20Aligner-E8C32E" alt="Demo - Qur'anic Universal Aligner"></a>
  <a href="https://hetchyy-quranic-universal-audio.hf.space/"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Website-Qur'anic%20Universal%20Audio-E8C32E" alt="App - Qur'anic Universal Audio"></a>
  <a href="https://huggingface.co/datasets/hetchyy/quranic-universal-ayahs"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Dataset-Qur'anic%20Universal%20Ayahs-E8C32E" alt="Dataset - Qur'anic Universal Ayahs"></a>
  <!-- stats-badges:start -->
  <br>
  <a href="data/RECITERS.md"><img src="https://img.shields.io/badge/Recitations-9-d4842a" alt="Published recitations"></a>
  <a href="data/RECITERS.md"><img src="https://img.shields.io/badge/Riwayat-16-f0ad4e" alt="Catalog riwayat"></a>
  <a href="data/RECITERS.md"><img src="https://img.shields.io/badge/Hours-250h%2B-d4842a" alt="Published audio hours"></a>
  <!-- stats-badges:end -->
  <br>
  <a href="https://github.com/Wider-Community/quranic-universal-audio/releases/latest"><img src="https://img.shields.io/github/v/release/Wider-Community/quranic-universal-audio?label=Release&color=4a5568" alt="Latest Release"></a>
  <a href="https://github.com/Wider-Community/quranic-universal-audio"><img src="https://img.shields.io/github/stars/Wider-Community/quranic-universal-audio?style=social" alt="GitHub stars"></a>
  <a href="https://discord.gg/cZ3V2FynXz"><img src="https://img.shields.io/badge/Discord-Join-5865f2?logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">The all-in-one audio and timing hub for Qur'anic apps, developers, and researchers. A timestamps visualizer, editing tool and community-verified dataset unifying recitations at scale with word- and letter-level timestamps.</p>

## Key Highlights

- **Unified Qur'anic audio hub:** A single consistent schema with comprehensive metadata for reciters and recitations instead of scattered websites, CDN APIs, YouTube playlists, and raw files with different formats.

- **Large-scale, multi-riwayah, multi-style:** Full Qur'an coverage for hundreds of recitations and thousands of hours spanning mujawwad, murattal, muallim, taraweeh and children repeat styles, and different riwayat.

- **Phoneme-first alignment:** 20ms phoneme-level precision eliminates ambiguity at word boundaries and disambiguate tajweed effects where sounds merge across words.

- **Repetition-safe, gap-free timestamps:** The pipeline transcribes each silence-based segment independently, so repeated words/verses are detected and timestamped correctly. See the [comparison with QUL timestamps](docs/qul_vs_mfa_timestamps.md).

- **Community-driven validation:** No trusting a black-box pipeline. Every stage is automatically checked by dedicated validators and human-correctable through an interactive editing UI. Review flagged errors like missing words or misaligned boundaries, fix them visually, and feed corrections back into the dataset.

- **Submit your own recitations:** Add your favorite reciters and different audio sources to the catalog and we handle the processing — typically within a few days.

- **Comprehensive metadata and versioning:** Each recitation is governed by consistent schemas and metadata and versioned with a full history to track segment updates and timestamp corrections over time.

<!-- ## How we compare -->

<!-- ## Data Access -->

## Technical Overview

<p align="center">
  <img src="docs/quranic_universal_aligner_pipeline.svg" alt="Pipeline diagram">
</p>

| Component | Description |
|-----------|-------------|
| [`Quranic Universal Aligner`](https://huggingface.co/spaces/hetchyy/quranic-universal-aligner) | Demo running on Hugging Face GPU demonstrating our alignmnet toolkit, also available via [API](docs/client_api.md) |
| [`inspector/`](inspector/) | Entry website for browsing reciters, viewing timestmaps interactively and editing alignment results |
| [quranic-phonemizer](https://github.com/Hetchy/Quranic-Phonemizer) | External package — Qur'an-specific G2P; the foundation that allows phoneme-level alignment |

## Contributing

Visit the [website](https://hetchyy-quranic-universal-audio.hf.space/) and read the overview info and editing guide to get started in contributing recitations and reviewing.

Issues and pull requests are welcome. If you've found a bug or have a feature idea, open an [issue](https://github.com/Wider-Community/quranic-universal-audio/issues) or jump into the Discord.

To contribute code to the webapp directly, fork the repo and see [inspector/README.md](inspector/README.md) for setup instructions.

## License

[CC BY 4.0](LICENSE) — free to share and adapt with attribution.
