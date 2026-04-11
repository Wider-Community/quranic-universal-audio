# Contributing

Jazaka Allahu khayran for your interest in contributing to Qur'anic Universal Audio! This guide will help you get started regardless of your technical background.

## How the pipeline works

Every reciter goes through these steps:

1. **Request** — someone [submits a reciter](https://huggingface.co/spaces/hetchyy/Quran-reciter-requests) for processing 
2. **Segmentation** — the AI pipeline splits audio into pause (waqf) segments and matches them to Qur'anic text
3. **Review** — a human reviews the segments in the Inspector UI, fixing any flagged errors the AI might have made *(this is the main manual step)*
4. **Timestamps** — word/letter/phoneme timestamps are generated automatically after the reviewing is reviewed and accepted
5. **Release** — the reciter is automatically added to the [dataset](https://huggingface.co/datasets/hetchyy/quranic-universal-ayahs), and animated recitations can be viewed in the [Inspector UI](inspector/README.md)
6. **Ongoing refinement** — further review, re-processing, and timestamp updates as needed whenever any issues are detected later

## Reciter states

Reciters in the project fall into one of three states. Browse the full list in [RECITERS.md](data/RECITERS.md).

- **Not yet in the system** — audio exists online but hasn't been added to the repository
- **In the system, awaiting request or review** — audio exists; may be waiting for pipeline processing or human reviewing. Browse [issues needing a reviewer](https://github.com/Wider-Community/quranic-universal-audio/issues?q=is%3Aopen+label%3Areviewer-needed) or [issues with a reviewer assigned](https://github.com/Wider-Community/quranic-universal-audio/issues?q=is%3Aopen+label%3Areviewer-assigned)
- **Timestamped** — alignmnet results have been reviewed and timestamps generated; available in the [dataset](https://huggingface.co/datasets/hetchyy/quranic-universal-ayahs) and [Github Releases](https://github.com/Wider-Community/quranic-universal-audio/releases). Browse [completed issues](https://github.com/Wider-Community/quranic-universal-audio/issues?q=label%3Astatus%3Acompleted) or aligned reciters in the [index](https://github.com/Wider-Community/quranic-universal-audio/blob/main/data/RECITERS.md#aligned-reciters)

## Ways to contribute

1. **Request processing** — For reciters already in the system, determine a suitable silence threshold and submit a request [via the form](https://huggingface.co/spaces/hetchyy/Quran-reciter-requests) (see the [requesting a reciter](docs/requesting-a-reciter.md) guide). You can optionally volunteer to review the segments yourself — if not, one of our active contributors will handle the review. 
3. **Review alignmnet** — Listen to audio in the Inspector and fix alignmnet errors. No Qur'an expertise required — just adequate proficiency in reading and hearing the Qur'an
   - **a) Review new segments** — Pick up a reciter that hasn't been reviewed yet and fix automatically flagged errors and do quality checks.
   - **b) Refine timestamped reciters** — For reciters that already have timestamps, do additional quality checks and fix any remaining issues. Updates flow automatically to the dataset
   - **c) Review timestamps quality** — View word/letter highlighting animations and report any issues with timing or alignment quality. Fixing timestamps directly is not currently supported, but your feedback helps us improve the pipeline and catch any edge cases. 
4. **Report issues and suggest improvements** — Bug reports, feature ideas, and general feedback via [GitHub Issues](https://github.com/Wider-Community/quranic-universal-audio/issues)

## Setup

For reviewing alignment in the Inspector, you'll need Git and Python.

### Prerequisites

<details>
<summary><b>Installing Git</b></summary>

- **Windows:** Download from [git-scm.com](https://git-scm.com/download/win). The installer includes Git Bash, a terminal you can use for all commands below.
- **Mac:** Run `xcode-select --install` in Terminal. Alternatively, if you have [Homebrew](https://brew.sh): `brew install git`.
- **Linux:** `sudo apt install git` (Ubuntu/Debian) or `sudo dnf install git` (Fedora).

Verify: `git --version`

New to Git? GitHub's [Get Started guide](https://docs.github.com/en/get-started/getting-started-with-git) covers the basics.

</details>

<details>
<summary><b>Installing Python</b></summary>

- **Windows:** Download from [python.org/downloads](https://www.python.org/downloads/). During installation, **check "Add Python to PATH"**. Avoid the Microsoft Store version.
- **Mac:** `brew install python` (if you have [Homebrew](https://brew.sh)), or download from [python.org/downloads](https://www.python.org/downloads/).
- **Linux:** `sudo apt install python3 python3-pip` (Ubuntu/Debian) or `sudo dnf install python3 python3-pip` (Fedora).

Verify: `python3 --version` (should print 3.10 or higher)

> **Windows note:** If `python3` isn't recognized, try `python --version` instead.

</details>

<details>
<summary><b>(Optional) ffmpeg</b></summary>

Used for smoother editing in the Inspector. See the [Inspector README](inspector/README.md#setup) for installation instructions.

</details>

### Clone and install

Run the following in a terminal:

```bash
# Clone the repository
git clone https://github.com/Wider-Community/quranic-universal-audio.git
cd quranic-universal-audio

# Install the Inspector dependencies
pip install -r inspector/requirements.txt
```

## How to review results

There are two ways to get started:

**If you submitted a reciter request** and chose to review yourself on the form, you'll receive a confirmation email and another email when alignmnet has finished processing and is ready for review.

**If you'd like to review an existing reciter**, browse [issues needing a reviewer](https://github.com/Wider-Community/quranic-universal-audio/issues?q=is%3Aopen+label%3Areviewer-needed) and comment `/claim` on the one you'd like to work on. If you're already a repository collaborator, you'll be assigned immediately. If not, you'll receive a collaborator invite — accept it on GitHub, then comment `/confirm` to get assigned.

Once the alignment has been processed, you will be automatically assigned to the [pull request](https://github.com/Wider-Community/quranic-universal-audio/pulls).

**1. Check out the pull request branch**

```bash
git pull origin main                            # get latest updates
git branch -r                                   # list available branches
git checkout feat/add-segments-mishary-alafasi  # switch to the PR branch
```

**2. Run the Inspector**

```bash
python inspector/server.py # or python3 inspector/server.py
```

Open http://localhost:5000 to start editing. See the [Inspector README](inspector/README.md) for detailed documentation, visual guides, and the full review workflow.

**3. Push your fixes**

As you fix errors, save your changes and push. You can push multiple rounds of fixes.

```bash
git add data/recitation_segments/<reciter>/
git commit -m "fix: correct segmentation errors for <reciter>"
git push
```

**4. Mark as ready**

When you're satisfied, click **"Ready for review"** on the pull request page on GitHub. After we merge it, timestamps are generated automatically and the reciter is added to the dataset.

## Technical contributions

The ASR/MFA models are not currently public, so technical contributions to the core pipeline are limited. If you have ideas for technical collaboration, feel free to open an issue or reach out!
