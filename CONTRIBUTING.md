# Contributing

Jazaka Allahu khayran for your interest in contributing to Qur'anic Universal Audio! This guide will help you get started regardless of your technical background.

## How the pipeline works

Every reciter goes through these steps:

1. **Request** — someone [submits a reciter](https://huggingface.co/spaces/hetchyy/Quran-reciter-requests) for processing 
2. **Segmentation** — the AI pipeline splits audio into pause (waqf) segments and matches them to Qur'anic text
3. **Review** — a human reviews the segments in the Inspector UI, fixing any errors the AI made *(this is the main manual step)*
4. **Timestamps** — word/letter/phoneme timestamps are generated automatically after the reviewing is reviewed and accepted.
5. **Release** — the [dataset](https://huggingface.co/datasets/hetchyy/quranic-universal-ayahs) and GitHub Release are updated automatically, and animated recitations can be viewed in the inspector
6. **Ongoing refinement** *(optional)* — further review, re-processing, and timestamp updates as needed

## Reciter states

Reciters in the project fall into one of three states:

- **Available but not yet in the system** — audio exists online but hasn't been added to the repository
- **In the system, awaiting processing or review** — audio  exists; may be waiting for pipeline processing or for someone to review the AI-generated segments
- **Timestamped** — segments have been reviewed and timestamps generated; available in the [dataset](https://huggingface.co/datasets/hetchyy/quranic-universal-ayahs) and releases

## Ways to contribute

1. **Add a new reciter** — Find a reciter whose audio is available online and add them to the repository. See the [adding a reciter](docs/adding-a-reciter.md) guide
2. **Request processing** — For reciters already in the system, request that the AI pipeline runs on their audio using a suitable silence threshold. See the [requesting a reciter](docs/requesting-a-reciter.md) guide
3. **Review and refine segments** — Use the Inspector UI to listen to audio and fix AI errors so that timestamps can be generated. No technical knowledge or Qur'an expertise required — just general proficiency in reading and hearing the Qur'an. See the [Inspector README](inspector/README.md)
   - **a) Review new segments** — After processing, a draft pull request is created for each reciter. Check out the branch, fix errors, and push corrections. This is the main manual step and where help is most needed
   - **b) Refine timestamped reciters** — For reciters that already have timestamps, do additional quality checks and fix any remaining issues. Updates flow automatically to the dataset
4. **Report issues and suggest improvements** — Bug reports, feature ideas, and general feedback via [GitHub Issues](https://github.com/Wider-Community/quranic-universal-audio/issues)

## Prerequisites

Contributions 2 and 4 (requesting processing and reporting issues) only need a browser. For the rest, you'll need a **terminal**, **Git**, and **Python 3.10+**.

<details>
<summary><b>Installing Git</b></summary>

- **Windows:** Download from [git-scm.com](https://git-scm.com/download/win). The installer includes Git Bash, a terminal you can use for all commands below.
- **Mac:** Run `xcode-select --install` in Terminal. Alternatively, if you have [Homebrew](https://brew.sh): `brew install git`.
- **Linux:** `sudo apt install git` (Ubuntu/Debian) or `sudo dnf install git` (Fedora).

Verify: `git --version`

New to Git? GitHub's [Get Started guide](https://docs.github.com/en/get-started/getting-started-with-git) covers the basics.

</details>

<details>
<summary><b>Installing Python (3.10 or newer)</b></summary>


- **Windows:** Download from [python.org/downloads](https://www.python.org/downloads/). During installation, **check "Add Python to PATH"**. Avoid the Microsoft Store version.
- **Mac:** `brew install python` (if you have [Homebrew](https://brew.sh)), or download from [python.org/downloads](https://www.python.org/downloads/).
- **Linux:** `sudo apt install python3 python3-pip` (Ubuntu/Debian) or `sudo dnf install python3 python3-pip` (Fedora).

Verify: `python3 --version` (should print 3.10 or higher)

> **Windows note:** If `python3` isn't recognized, try `python --version` instead.

If you run into trouble, see Python's [official setup guide](https://docs.python.org/3/using/index.html).

</details>

## General workflow

Contributions happen through **GitHub pull requests**:

1. **Fork** the repository on GitHub (click the Fork button on the [repo page](https://github.com/Wider-Community/quranic-universal-audio))
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/<your-username>/quranic-universal-audio.git
   cd quranic-universal-audio
   ```
3. Make your changes on a new branch
4. Git push and open a **pull request** against `main` from the Github Pull Requests tab

For **segment review**, the workflow is slightly different — a draft PR is created automatically for each reciter after processing, and you push fixes directly to that branch. See the [Inspector README](inspector/README.md) for the full editing workflow.

## Technical contributions

The ASR and forced alignment models are not currently public, so technical contributions to the core pipeline are limited. If you have ideas for technical collaboration, feel free to reach out!
