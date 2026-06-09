# Commit

Automatically commit at the completion of a task/feature only without being asked.

## Commit Message Format

```
prefix(scope): imperative description
1-2 concise detail
```
- Lowercase prefix
- Subject ≤72 chars. Name the unit then the change: `prefix(scope): <target> — <what>` (e.g. `<target>` = the script/file/function). 
- Short comprehensive detail in the body, not crammed into the subject. 1 sentence default. 2 for bigger commits.
- Do not commit as Claude or say co-authored by Claude

### Prefixes

`feat`, `fix`, `docs`, `agents`, `chore`, `refactor`, `test`, `style`, `perf`, `ci`, `build`, `revert`, etc.

### Scopes

Format as `<prefix>(<area(s)>-<concern(s)>)`

Areas: `board`, `admin`, `segs`, `ts`, `global`, `jobs`, `releases`

Concerns (optional): `ui`, `fe`, `be`, `db`, `audio`

Not every area needs a concern necessarily

## PRs

PR titles follow the same format

## Gitignored 

`.local/`