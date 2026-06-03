# Frontmatter Reference

Subagent files are Markdown with YAML frontmatter. Only `name` and `description` are required. The Markdown body is the system prompt.

```markdown
---
name: code-reviewer
description: Reviews code for quality and best practices
tools: Read, Glob, Grep
model: sonnet
---

You are a code reviewer. When invoked, analyze the code...
```

Subagents receive only this system prompt plus basic environment info (cwd) — no Claude Code default system prompt. Working directory is the parent's cwd; `cd` does not persist between Bash calls. For an isolated repo copy use `isolation: worktree`.

## Supported fields

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Unique identifier, lowercase + hyphens. |
| `description` | Yes | When Claude should delegate. Primary trigger signal. |
| `tools` | No | Allowlist. Inherits all tools if omitted. Comma-separated names. Supports `Agent(name1, name2)` for main-thread spawn restriction. |
| `disallowedTools` | No | Denylist. Applied before `tools` resolves. |
| `model` | No | `sonnet` \| `opus` \| `haiku` \| full ID (e.g. `claude-opus-4-7`) \| `inherit`. Default: `inherit`. |
| `permissionMode` | No | `default` \| `acceptEdits` \| `auto` \| `dontAsk` \| `bypassPermissions` \| `plan`. Ignored for plugin subagents. |
| `maxTurns` | No | Cap on agentic turns before subagent stops. |
| `skills` | No | List of skill names to inject at startup. Full content injected, not just availability. Skills don't inherit from parent. |
| `mcpServers` | No | List. Each entry: a string (referencing already-configured server) or inline `{name: <config>}` matching `.mcp.json` schema. Ignored for plugin subagents. |
| `hooks` | No | Lifecycle hooks scoped to this subagent. Ignored for plugin subagents. |
| `memory` | No | `user` \| `project` \| `local`. Enables persistent memory directory + auto-enables Read/Write/Edit. |
| `background` | No | `true` to always run as background task. Default `false`. |
| `effort` | No | `low` \| `medium` \| `high` \| `xhigh` \| `max` (model-dependent). Overrides session effort. |
| `isolation` | No | `worktree` to run in a temporary git worktree. Auto-cleaned if no changes made. |
| `color` | No | Display color: `red`, `blue`, `green`, `yellow`, `purple`, `orange`, `pink`, `cyan`. |
| `initialPrompt` | No | Auto-submitted as first user turn when agent runs as main session via `--agent`. Slash commands and skills are processed. Prepended to user prompt. |

## Model resolution order

1. `CLAUDE_CODE_SUBAGENT_MODEL` env var
2. Per-invocation `model` parameter from Agent tool call
3. Subagent's `model` frontmatter
4. Main conversation's model

## Plugin subagent restrictions

Plugin-loaded subagents ignore `hooks`, `mcpServers`, `permissionMode`. Copy the file into `.claude/agents/` or `~/.claude/agents/` if those fields are needed.
