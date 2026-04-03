## 03/04/2026

- **Inline reference editing** — click any segment's reference to edit it directly
  - Supports full refs (2:255:1-2:255:5), short forms (2:255:1-5), whole verses (2:255), verse ranges (2:255-2:256), and special keywords (Basmala, Isti'adha, Amin, Takbir, Tahmeed, Tasleem, Sadaqa)
  - Automatically updates "Missing Words" flags on neighbouring segments when a reference changes
  - Can convert between segment types — e.g. re-label a misidentified segment as a special keyword or vice versa
- **Repetition detection** — single segments where the reciter repeated words  are now automatically detected and flagged with a "Repeated Words" badge
  - Accounts for segmentation failures and undetected pauses. If you see many repetitions, try re-segmenting with a lower silence threshold to split them out
  - Each repeated section is shown on its own line, and repetition data is included in the JSON output
  - Provide feedback with the ✓ / ✗ buttons to help improve the feature and its accuracy
  - *Coming soon: auto-split repetitions into separate cards with aligned audio*

## 29/03/2026

- Settings panels now auto-collapse after extraction to reduce clutter, and re-expand when new audio is loaded
- Fixed crash on very long recordings (few hours), added warning message upon upload
- Added URL input mode — paste a link to download audio directly
- API calls are faster — skipped unnecessary audio processing for JSON-only responses
