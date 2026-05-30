# About Qur'anic Universal Audio

Qur'anic Universal Audio is a project to generate accurate word- and letter-level timestamps for Qur'an recitations at scale — community-verified and constantly updating.

Doing that well depends on a second goal: unifying recitations in one place. We collect reciters, normalize their metadata, and bring together their different styles, channels, and versions under a single catalog. From there, anyone can contribute — submit a new recitation, edit a reciter's metadata, or review the generated alignment.

## How it works

Machines draft, people verify. Each recitation is automatically split into segments at the reciter's pauses and matched to the Qur'anic text. A reviewer then listens through and corrects whatever the pipeline missed. Only once the segments are clean are the precise word- and letter-level timestamps generated — doing that last is what keeps them accurate. Verified reciters are published to the open dataset, and the work continues as new recitations arrive.

## Lifecycle

Every reciter carries a status that shows where it is on that path:

::lifecycle
- available_for_request: The audio is catalogued, but no one has requested alignment yet.
- requested: Alignment has been requested; the pipeline is processing the audio.
- available_for_review: Alignment is done and waiting for someone to claim and check it.
- under_review: A contributor has claimed it and is correcting the segments.
- published: Reviewed, timestamped, and live in the dataset for anyone to use.

## Finding your way around

- **Dashboard** — the front door. Browse and search reciters, listen to audio, and follow recent activity.
- **Timestamps** — the output. For published reciters, play the recitation with word- and letter-level highlighting and inspect the segment breakdown.
- **Segments** — where reviewing happens, the middle of the pipeline. Segments are edited and fixed here first; timestamps come only afterward, which is what keeps them accurate.
