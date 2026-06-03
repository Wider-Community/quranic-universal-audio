# Forked Subagents

Experimental, requires Claude Code v2.1.117+. Enable: `CLAUDE_CODE_FORK_SUBAGENT=1` (interactive, SDK, `claude -p`).

A fork is a subagent that **inherits the entire conversation so far** instead of starting fresh. Same system prompt, tools, model, and message history as the main session. The fork's tool calls stay out of main context; only the final result returns.

Use forks when:
- A named subagent would need too much background to be useful
- Trying multiple approaches in parallel from the same starting point

## What enabling fork mode changes

- Claude spawns a fork wherever it would otherwise use the **general-purpose** built-in subagent. Named subagents (Explore, etc.) still spawn normally.
- Every subagent spawn (fork or named) runs in the background. Set `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` to keep spawns synchronous.
- `/fork` spawns a fork instead of being an alias for `/branch`.

## Manual fork

```
/fork draft unit tests for the parser changes so far
```

Claude Code names the fork from the directive's first words. Fork appears in a panel below the prompt and runs in background. Final result arrives as a message in main conversation.

## Panel controls

| Key | Action |
|---|---|
| `↑` / `↓` | Move between rows |
| `Enter` | Open fork transcript, send follow-ups |
| `x` | Dismiss finished / stop running fork |
| `Esc` | Return to prompt input |

## Fork vs named subagent

| | Fork | Named subagent |
|---|---|---|
| Context | Full conversation history | Fresh context + passed prompt |
| System prompt + tools | Same as main session | From definition file |
| Model | Same as main session | From `model` field |
| Permissions | Prompts surface in terminal | Pre-approved upfront, then auto-denied |
| Prompt cache | Shared with main session | Separate cache |

Because fork shares prompt + tool defs with parent, first request reuses parent's prompt cache — cheaper than fresh subagent for context-heavy tasks.

When Claude spawns a fork via the Agent tool it can pass `isolation: "worktree"` so file edits go to a separate git worktree.

## Limitations

- Forks cannot spawn further forks.
