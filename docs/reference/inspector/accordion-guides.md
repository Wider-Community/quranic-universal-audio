# Accordion Guides

Frontend-authored guide templates for validation accordion help modals.

## Location

| Path | Purpose |
|---|---|
| `inspector/frontend/src/tabs/segments/guides/accordion/*.guide.ts` | Markdown-like guide source by validation category |
| `inspector/frontend/src/tabs/segments/guides/examples/index.ts` | Typed, reusable history-card examples |
| `inspector/frontend/src/tabs/segments/guides/parser.ts` | Limited guide syntax parser |

## Guide Syntax

```md
# Low Confidence

Natural paragraph text.

::example{id="low_conf_reference_correction"}

More text.

::example{id="low_conf_trim_timing"}
::example{id="low_conf_split_phrase"}
```

| Syntax | Renders as |
|---|---|
| `# Heading` | Modal title |
| `## Heading` | Section heading |
| Paragraphs separated by blank lines | Body copy |
| `::example{id="..."}` | Shared History card renderer |

## Example Records

Each example carries `id`, `title`, optional `description`, `render`, `chapter`,
`operations`, and optional `peaks`.

History snapshots inside `operations` include `audio_url`, `time_start`,
`time_end`, `matched_ref`, `confidence`, `segment_uid`, and `index_at_save`.
Peaks use the existing per-op shape: `op_id`, `url`, `start_ms`, `end_ms`,
`duration_ms`, `peaks`.

## Read Path

The modal reads guide source and examples from the frontend bundle. No backend
route or bucket file is involved.

## Validation

Frontend tests cover parser order, malformed directives, modal rendering, and
history examples without edit controls.
