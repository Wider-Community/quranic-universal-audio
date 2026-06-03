---
name: subagent-guidance
description: Guidance for creating and configuring custom Claude Code subagents/teams. Use when the user wants to create, edit, debug or choose between subagents and alternatives (e.g. skills).
---

# Subagent Guidance

A subagent is a specialized agent with its own context window, system prompt, tool allowlist, and permissions. Claude Code delegates to it via the Agent tool. Use this skill to help the user design and ship one.

## When subagents are the right tool

Recommend a subagent when:
- The task floods main context with output the user won't reuse (test logs, search dumps, doc fetches).
- The user keeps spawning the same kind of worker with the same instructions — codify it.
- The work needs tighter tool/permission restrictions than the main session.
- Independent investigations can run in parallel.

Recommend something else when:
- Reusable prompt/workflow that should run in main context → **Skill**.
- Sustained parallelism with workers that need to **communicate with each other**, share a task list, or debate findings → **agent teams** (see `references/agent-teams.md`).
- Quick question about current conversation → **`/btw`**.
- Side task that needs full prior context → **fork** (see `references/forks.md`).
- Nested delegation needed — subagents cannot spawn subagents.

## Authoring workflow

Follow these steps when creating a new subagent. Skip ahead if the user already has a draft.

1. **Capture intent.** Ask (or infer): what task, when should Claude delegate, what tools are needed, what's returned. If the user is non-technical, prefer the `/agents` interactive command and walk them through it.
2. **Choose scope.** Project (`.claude/agents/`) for repo-specific + version-controlled. User (`~/.claude/agents/`) for cross-project personal. Plugin for distribution. CLI `--agents` JSON for ephemeral. See `references/scope-and-files.md` for priority order and the file format.
3. **Write the file.** YAML frontmatter + Markdown system prompt. Required fields: `name`, `description`. See `references/frontmatter.md` for every supported field — consult it before adding any field beyond name/description/tools/model.
4. **Restrict tools.** Default inherits everything. Use `tools` (allowlist) or `disallowedTools` (denylist). For read-only reviewers: `tools: Read, Grep, Glob, Bash`. For Agent-spawning restriction (main-thread agents only) use `Agent(name1, name2)` syntax.
5. **Pick a model.** `inherit` (default), `sonnet`, `opus`, `haiku`, or full ID. Use Haiku for cheap/fast routing tasks, Sonnet for analysis, inherit for general work.
6. **Write the system prompt.** Imperative voice. Tell it what to do *when invoked*, the workflow, and the output format. Keep focused — one job per subagent. The prompt becomes the entire system prompt (no Claude Code defaults inherited besides cwd).
7. **Tune the description.** This is the trigger. Make it specific about *when* Claude should delegate. Include phrases like "use proactively" if you want eager delegation.
8. **Reload.** Subagents load at session start. After manual file creation tell user to restart or run `/agents` to pick it up.

## Description writing

The `description` is the only thing Claude sees when deciding to delegate. Pattern:

```
[Role/expertise]. [What it does]. [When to invoke — concrete contexts].
```

Bad: `Reviews code.`
Good: `Expert code review specialist. Reviews diffs for quality, security, and maintainability. Use proactively immediately after writing or modifying code.`

## Common patterns

- **Isolate high-volume work** — tests, log scanning, doc fetches. Subagent returns a summary only.
- **Parallel research** — spawn multiple in one turn for independent investigations.
- **Chain** — output of one subagent feeds the next via main thread.
- **Background** — concurrent execution; permissions pre-approved upfront. See `references/invocation.md`.

## Advanced configuration

Consult the matching reference only when the user asks for it:

- **`references/frontmatter.md`** — full field table (every supported key, types, defaults).
- **`references/scope-and-files.md`** — file locations, priority, `--agents` CLI JSON, plugin caveats, managed settings.
- **`references/permissions-and-tools.md`** — `tools`/`disallowedTools` resolution, `Agent(...)` allowlist, `permissionMode` modes, hook-based conditional rules, disabling subagents.
- **`references/hooks.md`** — frontmatter hooks (PreToolUse/PostToolUse/Stop→SubagentStop), settings.json SubagentStart/Stop, validation script pattern.
- **`references/mcp-skills-memory.md`** — `mcpServers` inline vs reference, `skills` preloading, `memory` scopes (user/project/local).
- **`references/invocation.md`** — automatic delegation, natural language, `@`-mention, `--agent` for whole session, foreground vs background, resume via `SendMessage`, auto-compaction.
- **`references/forks.md`** — fork mode (`CLAUDE_CODE_FORK_SUBAGENT=1`), `/fork`, fork vs named subagent comparison, panel controls.
- **`references/built-in.md`** — Explore, Plan, general-purpose, statusline-setup, Claude Code Guide.
- **`references/examples.md`** — code-reviewer, debugger, data-scientist, db-reader (with hook validation script).
- **`references/agent-teams.md`** — agent teams (experimental): when to choose teams over subagents, lead/teammate architecture, shared task list, mailbox, display modes (in-process / split panes / tmux / iTerm2), spawning teammates from subagent definitions, plan approval gating, `TeammateIdle`/`TaskCreated`/`TaskCompleted` hooks, cleanup, limitations.

## Output checklist

Before handing back a finished subagent, verify:
- `name` is lowercase-hyphenated and unique within scope.
- `description` names concrete trigger contexts.
- Tool list is minimal for the job.
- System prompt explains *workflow* and *output format*, not just role.
- File is in the right scope directory; tell the user to reload the session.
