# Commit

Autonomously commit at the completion of a task/feature.

## Commit Message Format

- Subject ≤72 chars. Name the unit then the change: `prefix(scope): <target> — <what>` (e.g. `<target>` = the script/file/function). 
- Short comprehensive 1 sentence detail in the body.
- No Claude attribution.

### Prefixes

`feat`, `fix`, `docs`, `agents`, `chore`, `refactor`, `test`, `style`, `perf`, `ci`, `build`, `revert`, etc.

### Scopes

Format as `<prefix>(<area(s)>-<concern(s)>)`

Areas: `board`, `admin`, `segs`, `ts`, `global`, `jobs`, `releases`

Concerns (optional): `ui`, `fe`, `be`, `db`, `audio`

Not every area needs a concern necessarily

## Gitignored 

`.local/`