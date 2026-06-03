# MCP Servers, Skills, and Memory

## mcpServers

Give the subagent MCP access not in main conversation. Inline servers connect at subagent start, disconnect at finish. String entries reuse parent's connection.

```yaml
---
name: browser-tester
description: Test features in a real browser
mcpServers:
  - playwright:
      type: stdio
      command: npx
      args: ["-y", "@playwright/mcp@latest"]
  - github  # references existing server
---
```

Inline schema = `.mcp.json` entries (`stdio`, `http`, `sse`, `ws`), keyed by server name.

To keep an MCP out of the main conversation entirely (and avoid its tool descriptions consuming parent context), define inline here instead of in `.mcp.json`.

Field also applies when the agent runs as main session via `--agent`/`agent` setting — inline servers connect alongside `.mcp.json` servers. Ignored for plugin subagents.

## Preloaded skills

`skills` injects full skill content into the subagent's context at startup. Subagents do not inherit skills from parent — list explicitly.

```yaml
---
name: api-developer
description: Implement API endpoints following team conventions
skills:
  - api-conventions
  - error-handling-patterns
---
```

Cannot preload skills with `disable-model-invocation: true`. Missing/disabled skills are skipped with a debug-log warning.

This is the inverse of a skill's `context: fork` (which injects skill content into a target agent). Same underlying system.

## Persistent memory

`memory` gives the subagent a directory that survives across conversations.

| Scope | Location | Use when |
|---|---|---|
| `user` | `~/.claude/agent-memory/<name>/` | Cross-project learnings |
| `project` | `.claude/agent-memory/<name>/` | Project-specific, version-controlled |
| `local` | `.claude/agent-memory-local/<name>/` | Project-specific, NOT version-controlled |

When enabled:
- Memory instructions added to system prompt.
- First 200 lines or 25KB of `MEMORY.md` (whichever first) injected, with curation instructions if exceeded.
- Read/Write/Edit auto-enabled.

```yaml
---
name: code-reviewer
description: Reviews code for quality
memory: user
---

You are a code reviewer. As you review, update agent memory with patterns,
conventions, and recurring issues.
```

### Memory tips

- Default to `project` for shareability.
- Ask the subagent to consult memory before work and update after.
- Embed memory-curation instructions in the system prompt so it self-maintains.
