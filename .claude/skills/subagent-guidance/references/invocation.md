# Invocation, Foreground/Background, and Resume

## Automatic delegation

Claude decides based on user request, current context, and the subagent's `description`. Phrases like "use proactively" in the description encourage eager delegation.

## Explicit invocation — three escalating patterns

### Natural language

Name it in the prompt; Claude usually delegates:

```
Use the test-runner subagent to fix failing tests
```

### @-mention (guarantees that subagent runs)

```
@"code-reviewer (agent)" look at the auth changes
```

Type `@` and pick from typeahead. Plugin agents appear as `<plugin>:<agent>`. Manual form: `@agent-<name>` or `@agent-<plugin>:<agent>`. The full message still goes to Claude — the @-mention only controls *which* subagent is invoked, not the prompt it receives.

### Whole session as a subagent

```bash
claude --agent code-reviewer
```

Subagent's system prompt fully replaces the Claude Code default (like `--system-prompt`). `CLAUDE.md` and project memory still load via message flow. Header shows `@<name>`. Persists across resume.

For plugin agents: `claude --agent <plugin>:<agent>`.

Project default in `.claude/settings.json`:

```json
{ "agent": "code-reviewer" }
```

CLI flag overrides setting.

## Foreground vs background

| Mode | Behavior |
|---|---|
| Foreground | Blocks main conversation. Permission prompts and `AskUserQuestion` pass through. |
| Background | Concurrent. Permissions pre-approved upfront; auto-deny anything else. Clarifying-question tool calls fail but subagent continues. |

If background fails on missing permissions, retry the same task with a foreground subagent for interactive prompts.

Trigger background:
- Ask Claude to "run this in the background"
- Press **Ctrl+B** to background a running task
- Set `background: true` in frontmatter

Disable all background tasks: `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`.

When fork mode is on, every spawn is background regardless of the field. Forks still surface permission prompts as they occur (no pre-approval).

## Common patterns

**Isolate high-volume operations:**
```
Use a subagent to run the test suite and report only the failing tests with errors
```

**Parallel research:**
```
Research the auth, database, and API modules in parallel using separate subagents
```

Each subagent's full result returns to main context — many parallel subagents with verbose results can still bloat context. For sustained parallelism beyond context, prefer agent teams.

**Chain:**
```
Use the code-reviewer subagent to find perf issues, then use the optimizer to fix them
```

## Subagent vs main conversation

Main conversation when:
- Frequent back-and-forth or iterative refinement
- Multi-phase work shares context (planning → impl → testing)
- Quick targeted change
- Latency matters (subagents start fresh, gather context)

Subagent when:
- Verbose output not needed in main context
- Need tool/permission restrictions
- Self-contained, returns a summary

For a quick question about something already in context, use `/btw` (no tool access; answer not added to history).

## Resume

Each subagent invocation creates a fresh instance. To continue an existing one, ask Claude to resume — full prior history (tool calls, results, reasoning) is retained.

When a subagent finishes, Claude has its agent ID. Claude resumes via `SendMessage` (id in `to` field). `SendMessage` only available with agent teams enabled (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`).

```
Use the code-reviewer subagent to review auth module
[completes]
Continue that review and now analyze authorization logic
[Claude resumes with full prior context]
```

A stopped subagent receiving `SendMessage` auto-resumes in the background — no new `Agent` invocation needed.

Find IDs in `~/.claude/projects/{project}/{sessionId}/subagents/agent-{agentId}.jsonl`.

## Transcript persistence

- Main-conversation compaction does NOT affect subagent transcripts (separate files).
- Persist within session — resume after Claude Code restart by resuming the session.
- Auto-cleanup per `cleanupPeriodDays` (default 30).

## Auto-compaction

Subagents auto-compact at ~95% capacity. Override threshold with `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` (e.g. `50`). Logged in transcript:

```json
{ "type": "system", "subtype": "compact_boundary",
  "compactMetadata": { "trigger": "auto", "preTokens": 167189 }}
```
