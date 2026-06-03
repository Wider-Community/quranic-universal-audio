---
name: git-searcher
description: Token-cheap git/gh scripts to find prior commits/PRs by message and map sha→PR.
---

# git-searcher

Find a past commit or PR by its description, cheaply. Local `git log` does the
real searching (zero API); `gh` only attaches PR numbers or text-searches PR
bodies. Paired with the `git-searcher` subagent — it runs these so search dumps
never hit the main context.

`scripts/` (all print terse, newest-first, one match per line):

| Script | Cost | Does |
|---|---|---|
| `commits.sh "<q>" [flags]` | free (local) | message search, subject+body, case-insensitive |
| `prs.sh "<q>" \| --for-commit <sha>` | gh API | text-search merged PRs, or map a sha → its PR |
| `dig.sh <sha\|PR#> [--full]` | local/gh | OPT-IN diff; `--stat`/file-list default, `--full` last resort |

## Recipe

1. **Search commits first** — `commits.sh "<keywords>"`. Default whole query is
   one regex (`-E`), so `"modal|backdrop"` ORs. Add `--and` to require every
   word (`"board regenerate" --and`).
2. **Read the PR for free** — squash-merge subjects already carry `(#NN)`. Only
   call `prs.sh --for-commit <full-sha>` when that suffix is missing (direct
   push or merge commit). Use a **full** 40-char sha for the map to hit.
3. **PR-body search** — `prs.sh "<q>"` when the lead is a PR description, not a
   commit message.
4. **Dig only on request** — `dig.sh` is off by default; pointers let the caller
   open the diff themselves.

## Narrowing flags (commits.sh)

- `--since <date>` / `--until <date>` — "~X days ago" → `--since "X days ago"`.
- `--before <ref>` — history ending just before `<ref>` ("N PR merges before").
- `--skip N` — drop the N newest matches.
- `-n N` — cap output (default 15). `--author <x>`.
