# Built-in Subagents

Claude Code ships with these. They inherit parent permissions plus extra tool restrictions.

## Explore

- **Model:** Haiku (fast, low-latency)
- **Tools:** Read-only (denied Write, Edit)
- **Purpose:** File discovery, code search, codebase exploration

Claude delegates here for search/understanding without changes. Keeps exploration output out of main context. When invoking, Claude specifies thoroughness: `quick`, `medium`, or `very thorough`.

## Plan

- **Model:** Inherits from main
- **Tools:** Read-only
- **Purpose:** Codebase research during plan mode

Used in plan mode to gather context. Prevents infinite nesting (subagents can't spawn subagents) while still researching.

## General-purpose

- **Model:** Inherits from main
- **Tools:** All
- **Purpose:** Complex, multi-step work mixing exploration and modification

Claude delegates here when the task needs both exploration and changes, complex reasoning, or multiple dependent steps.

When fork mode is enabled, this is replaced by forks (see `forks.md`).

## Other helpers

| Agent | Model | When |
|---|---|---|
| `statusline-setup` | Sonnet | `/statusline` config |
| Claude Code Guide | Haiku | Questions about Claude Code features |

Auto-invoked. Don't address directly.
