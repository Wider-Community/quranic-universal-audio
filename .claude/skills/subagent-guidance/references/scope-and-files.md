# Scope, Locations, and File Management

## Priority order (highest to lowest)

| Location | Scope | Priority |
|---|---|---|
| Managed settings | Org-wide | 1 |
| `--agents` CLI flag | Current session | 2 |
| `.claude/agents/` | Current project | 3 |
| `~/.claude/agents/` | All your projects | 4 |
| Plugin `agents/` directory | Where plugin enabled | 5 |

When names collide, higher priority wins.

## Project subagents (`.claude/agents/`)

Repo-specific. Check into version control. Discovered by walking up from cwd. Directories added with `--add-dir` are NOT scanned for subagents — they grant file access only.

## User subagents (`~/.claude/agents/`)

Personal, all projects.

## CLI-defined subagents

Pass JSON at launch — session-only, never persisted:

```bash
claude --agents '{
  "code-reviewer": {
    "description": "Expert code reviewer. Use proactively after code changes.",
    "prompt": "You are a senior code reviewer...",
    "tools": ["Read", "Grep", "Glob", "Bash"],
    "model": "sonnet"
  }
}'
```

Same fields as file frontmatter, but the system prompt goes in `prompt` instead of the body. All frontmatter fields supported.

## Managed subagents

Org-deployed via `.claude/agents/` inside the managed settings directory. Same format. Override project + user.

## Plugin subagents

Installed via plugins. Appear in `/agents` UI. Cannot use `hooks`, `mcpServers`, or `permissionMode`.

## Listing

`claude agents` (non-interactive) lists all configured subagents grouped by source, indicating overrides.

## Loading

Subagents load at session start. After manually adding a file, restart the session or open `/agents` to pick it up.

## Cross-skill use

Subagent definitions are also visible to agent teams — when spawning a teammate by referencing a subagent type, the teammate uses its `tools` and `model`, with the body appended as additional system instructions.
