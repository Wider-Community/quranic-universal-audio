# About Qur'anic Universal Audio

## Overview

Qur'anic Universal Audio aims to generate accurate word- and letter-level timestamps for Qur'an recitations at scale — community-reviewed and constantly updating.

Doing that well depends on a second goal: unifying recitations in one place. We collect reciters, normalize their metadata, and bring together their different audio, styles, riwayahs, sources/channels, CDNs and versions under a single catalog. From there, anyone can contribute — submit a new recitation, edit a reciter's metadata, or review the generated alignment.

## How it works

Each recitation is run through our AI pipeline, automatically split into segments at the reciter's pauses and matched to the Qur'anic text. A reviewer then listens through and corrects whatever the pipeline missed and flagged as errors. 

A recitation is a combination of reciter x riwayah x style x channel x version/year, so the same reciter can have multiple recitations. Both full and partial mushaf recitations are available, although full mushaf recitations are preferred.

Only once the segments are clean, timestamps are generated and published (via API, HF dataset, JSON releases) — doing that last is what keeps them accurate. 

Any issues discovered after publication are simply fixed in the segments as usual, and timestamps are refreshed, which is what makes the pipeline iterative and self-correcting.

## Lifecycle

Every recitation carries a status that shows where it is on that path:

::lifecycle
- available_for_request: The audio is catalogued, but no one has requested alignment yet.
- requested: Alignment has been requested; the pipeline is processing the audio.
- available_for_review: Alignment is done and waiting for someone to claim and review the errors.
- under_review: A contributor has claimed it and is correcting the segments.
- published: Reviewed, timestamped, and live for anyone to use the data.

## Tabs

- **Dashboard** — the front door. Browse and search reciters, listen to audio, follow recent activity, and submit new recitations.
- **Timestamps** — the output. For published reciters, play the recitation with word- and letter-level highlighting alongside the waveform and do granular timestmaps analysis.
- **Segments** — where reviewing happens, the middle of the pipeline. Segments are edited and fixed here first before timestamps are generated. 

## Contributing 

Anyone is welcome to contribute — you just need to login with an account. The main ways to contribute are:

- **Requesting/submitting recitations:** review audio and metadata of catalogued recitations, or submit your own and contribute to the catalog and dataset. We typically process recitations within a few days.

- **Reviewing segments:** claim recitations that are available for review and fix any errors in the segments. Anyone can review, along as you are proficient enough in reading and understanding recitations.

- **Reviewing timestmaps:** while there is no formal way to edit timestamps directly, you can report any general issues that might be present with published reciters.

- **General feedback:** bug reports, feature requests, suggestions, and collaborations are welcome. Feel free to [open an issue on GitHub](https://github.com/Wider-Community/quranic-universal-audio/issues) or reach out directly.

- **Sharing the data and supporting the project.**

## Accessing the data

Coming soon