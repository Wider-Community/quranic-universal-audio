---
paths:
  - "data/**/*"
  - "docs/**/*"
  - "inspector/**/*"
  - "scripts/**/*"
  - ".github/**/*"
---

# Commit

Always commit regularly as you go at logical stop-points based on the changes made in the session. Do not wait to be asked to commit when you reach an obvious milestone

## Commit Message Format

```
prefix(scope): imperative description
1-3 concise bullet points
```
- Lowercase prefix
- Imperative mood after prefix e.g. `add`, `fix`
- Subject ≤72 chars. Name the unit then the change: `prefix(scope): <target> — <what>` (e.g. `<target>` = the script/file/function). Keep detail — parentheticals, `+`-lists, schema/field names — in the body, not crammed into the subject.
- Short comprehensive bullets — cover what changed, and briefly why
- Do not commit as Claude or say co-authored by Claude or attribution. Commit as user 
- Do not be verbose. 1-2 bullets default. 3 max for complex commits

### Prefixes

`feat`, `fix`, `docs`, `agents`, `chore`, `refactor`, `test`, `style`, `perf`, `ci`, `build`, `revert`, etc.

### Scopes

Format as `<prefix>(<area(s)>-<concern(s)>)`

areas: `board`, `admin` (admin dashboard), `segs`, `ts`, `global` for whole app, `jobs`, `releases`

concerns: `ui`, `fe`, `be`, `db`, `audio`, etc. or blank

- Use these area names, not component names — whole-app FE is `global-fe`.
- Join multiple areas/concerns with commas: `fix(board-be,ts-be,scripts)`
- Not every area needs a concern necessarily

## PRs

PR titles follow the same rule, since we squash-merge.

## Gitignored 

`.local/`